// Command gometrics measures what golangci-lint does not: package fan-in and
// fan-out, type cohesion (LCOM4), and code and comment lines per file. It reads
// the module in the working directory and writes JSON to stdout. Test files and
// generated files are not measured.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

type pkg struct {
	ImportPath string
	Dir        string
	Module     *struct{ Path, Dir string }
	GoFiles    []string
	Imports    []string
}

type packageMetrics struct {
	Package  string `json:"package"`
	Dir      string `json:"dir"`
	FanIn    int    `json:"fanin"`
	FanOut   int    `json:"fanout"`
	External int    `json:"external_imports"`
	Files    int    `json:"files"`
	Code     int    `json:"code_lines"`
}

type typeMetrics struct {
	Package string `json:"package"`
	File    string `json:"file"`
	Line    int    `json:"line"`
	Name    string `json:"name"`
	Methods int    `json:"methods"`
	LCOM4   int    `json:"lcom4"`
}

type fileMetrics struct {
	File     string `json:"file"`
	Code     int    `json:"code_lines"`
	Comments int    `json:"comment_lines"`
	Blank    int    `json:"blank_lines"`
}

type output struct {
	Module   string           `json:"module"`
	Packages []packageMetrics `json:"packages"`
	Types    []typeMetrics    `json:"types"`
	Files    []fileMetrics    `json:"files"`
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "gometrics:", err)
		os.Exit(1)
	}
}

func run() error {
	root, err := os.Getwd()
	if err != nil {
		return err
	}
	pkgs, err := list()
	if err != nil {
		return err
	}
	out := output{Packages: []packageMetrics{}, Types: []typeMetrics{}, Files: []fileMetrics{}}
	inModule := map[string]bool{}
	for _, p := range pkgs {
		if p.Module != nil {
			out.Module = p.Module.Path
		}
		inModule[p.ImportPath] = true
	}
	fanIn := map[string]int{}
	for _, p := range pkgs {
		for _, imp := range p.Imports {
			if inModule[imp] && imp != p.ImportPath {
				fanIn[imp]++
			}
		}
	}

	fset := token.NewFileSet()
	for _, p := range pkgs {
		pm := packageMetrics{Package: p.ImportPath, Dir: rel(root, p.Dir), FanIn: fanIn[p.ImportPath]}
		for _, imp := range p.Imports {
			switch {
			case inModule[imp]:
				pm.FanOut++
			case strings.Contains(strings.SplitN(imp, "/", 2)[0], "."):
				pm.External++
			}
		}
		var files []*ast.File
		var names []string
		for _, name := range p.GoFiles {
			path := filepath.Join(p.Dir, name)
			src, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			f, err := parser.ParseFile(fset, path, src, parser.ParseComments)
			if err != nil {
				return err
			}
			if ast.IsGenerated(f) {
				continue
			}
			fm := countLines(fset, f, src)
			fm.File = rel(root, path)
			out.Files = append(out.Files, fm)
			pm.Files++
			pm.Code += fm.Code
			files = append(files, f)
			names = append(names, fm.File)
		}
		if pm.Files == 0 {
			continue
		}
		out.Packages = append(out.Packages, pm)
		out.Types = append(out.Types, cohesion(fset, p.ImportPath, files, names)...)
	}
	sort.Slice(out.Types, func(i, j int) bool {
		return out.Types[i].Package+"."+out.Types[i].Name < out.Types[j].Package+"."+out.Types[j].Name
	})
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(out)
}

func list() ([]pkg, error) {
	cmd := exec.Command("go", "list", "-json=ImportPath,Dir,Module,GoFiles,Imports", "./...")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	raw, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("go list: %w: %s", err, stderr.String())
	}
	var pkgs []pkg
	dec := json.NewDecoder(bytes.NewReader(raw))
	for dec.More() {
		var p pkg
		if err := dec.Decode(&p); err != nil {
			return nil, err
		}
		pkgs = append(pkgs, p)
	}
	return pkgs, nil
}

func rel(root, path string) string {
	if r, err := filepath.Rel(root, path); err == nil {
		return filepath.ToSlash(r)
	}
	return path
}

// countLines classifies each line once. A line holding code and a trailing
// comment counts as code.
func countLines(fset *token.FileSet, f *ast.File, src []byte) fileMetrics {
	comment := map[int]bool{}
	for _, g := range f.Comments {
		for _, c := range g.List {
			start, end := fset.Position(c.Pos()).Line, fset.Position(c.End()).Line
			for l := start; l <= end; l++ {
				comment[l] = true
			}
		}
	}
	code := map[int]bool{}
	ast.Inspect(f, func(n ast.Node) bool {
		if n == nil {
			return false
		}
		switch n.(type) {
		case *ast.CommentGroup, *ast.Comment, *ast.File:
			return true
		}
		code[fset.Position(n.Pos()).Line] = true
		code[fset.Position(n.End()).Line] = true
		return true
	})
	code[fset.Position(f.Package).Line] = true

	var m fileMetrics
	sc := bufio.NewScanner(bytes.NewReader(src))
	sc.Buffer(make([]byte, 1024*1024), 1024*1024)
	for line := 1; sc.Scan(); line++ {
		text := strings.TrimSpace(sc.Text())
		switch {
		case text == "":
			m.Blank++
		case code[line] || !comment[line]:
			m.Code++
		default:
			m.Comments++
		}
	}
	return m
}

// cohesion computes LCOM4 for every type with methods: the number of groups of
// methods that share no receiver field and call no method of another group. A
// method that never touches its receiver joins no group, since it says nothing
// about how the type's state is shared.
func cohesion(fset *token.FileSet, pkgPath string, files []*ast.File, names []string) []typeMetrics {
	type method struct {
		name string
		uses map[string]bool
	}
	methods := map[string][]method{}
	decl := map[string]typeMetrics{}

	for i, f := range files {
		for _, d := range f.Decls {
			switch d := d.(type) {
			case *ast.GenDecl:
				for _, s := range d.Specs {
					if ts, ok := s.(*ast.TypeSpec); ok {
						decl[ts.Name.Name] = typeMetrics{
							Package: pkgPath, File: names[i], Line: fset.Position(ts.Pos()).Line, Name: ts.Name.Name,
						}
					}
				}
			case *ast.FuncDecl:
				if d.Recv == nil || len(d.Recv.List) == 0 || d.Body == nil {
					continue
				}
				typ := receiverType(d.Recv.List[0].Type)
				if typ == "" {
					continue
				}
				m := method{name: d.Name.Name, uses: map[string]bool{}}
				if len(d.Recv.List[0].Names) > 0 {
					recv := d.Recv.List[0].Names[0].Name
					ast.Inspect(d.Body, func(n ast.Node) bool {
						if sel, ok := n.(*ast.SelectorExpr); ok {
							if id, ok := sel.X.(*ast.Ident); ok && id.Name == recv {
								m.uses[sel.Sel.Name] = true
							}
						}
						return true
					})
				}
				methods[typ] = append(methods[typ], m)
			}
		}
	}

	var out []typeMetrics
	for typ, ms := range methods {
		t, ok := decl[typ]
		if !ok {
			continue
		}
		t.Methods = len(ms)
		index := map[string]int{}
		for i, m := range ms {
			index[m.name] = i
		}
		parent := make([]int, len(ms))
		for i := range parent {
			parent[i] = i
		}
		var find func(int) int
		find = func(i int) int {
			if parent[i] != i {
				parent[i] = find(parent[i])
			}
			return parent[i]
		}
		owner := map[string]int{}
		active := map[int]bool{}
		for i, m := range ms {
			for use := range m.uses {
				active[i] = true
				if j, isMethod := index[use]; isMethod {
					active[j] = true
					parent[find(i)] = find(j)
					continue
				}
				if j, seen := owner[use]; seen {
					parent[find(i)] = find(j)
				} else {
					owner[use] = i
				}
			}
		}
		groups := map[int]bool{}
		for i := range ms {
			if active[i] {
				groups[find(i)] = true
			}
		}
		t.LCOM4 = len(groups)
		out = append(out, t)
	}
	return out
}

func receiverType(e ast.Expr) string {
	switch t := e.(type) {
	case *ast.StarExpr:
		return receiverType(t.X)
	case *ast.Ident:
		return t.Name
	case *ast.IndexExpr:
		return receiverType(t.X)
	case *ast.IndexListExpr:
		return receiverType(t.X)
	}
	return ""
}
