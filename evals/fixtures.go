package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"gopkg.in/yaml.v3"
)

// Expect holds a fixture's assertions. Zero values mean "don't check".
type Expect struct {
	Escalate       *bool    `yaml:"escalate" json:"escalate,omitempty"`
	MaxChars       int      `yaml:"max_chars" json:"max_chars,omitempty"`
	ContainsAny    []string `yaml:"contains_any" json:"contains_any,omitempty"`
	MustNotContain []string `yaml:"must_not_contain" json:"must_not_contain,omitempty"`
	MustNotMatch   []string `yaml:"must_not_match" json:"must_not_match,omitempty"`
	// Require names result flags that must be true, e.g. builds, rows.
	Require []string `yaml:"require" json:"require,omitempty"`
}

// merge layers a fixture's expect over the stage defaults: scalars override,
// lists accumulate.
func (e Expect) merge(over Expect) Expect {
	out := e
	if over.Escalate != nil {
		out.Escalate = over.Escalate
	}
	if over.MaxChars > 0 {
		out.MaxChars = over.MaxChars
	}
	out.ContainsAny = append(append([]string{}, e.ContainsAny...), over.ContainsAny...)
	out.MustNotContain = append(append([]string{}, e.MustNotContain...), over.MustNotContain...)
	out.MustNotMatch = append(append([]string{}, e.MustNotMatch...), over.MustNotMatch...)
	out.Require = append(append([]string{}, e.Require...), over.Require...)
	return out
}

// Fixture is one case: an input for the robot and what a good output must do.
type Fixture struct {
	ID       string         `yaml:"id"`
	Category string         `yaml:"category"`
	Input    map[string]any `yaml:"input"`
	Expect   Expect         `yaml:"expect"`
}

// Stage is one boss fight: a task class with its fixtures.
type Stage struct {
	Stage      string    `yaml:"stage"`
	Robot      string    `yaml:"robot"`
	MemoryFile string    `yaml:"memory_file"`
	UVGroups   []string  `yaml:"uv_groups"` // extra dependency groups run_one needs
	Defaults   Expect    `yaml:"defaults"`
	Fixtures   []Fixture `yaml:"fixtures"`
	memory     string
}

// Contestant is a model fighting a stage: Mega Man, Proto Man, Bass, or the mock.
type Contestant struct {
	Name  string `yaml:"name"`
	Role  string `yaml:"role"`
	Brain string `yaml:"brain"`
}

func loadStage(dir, name string) (*Stage, error) {
	path := filepath.Join(dir, "stages", name+".yaml")
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var st Stage
	if err := yaml.Unmarshal(raw, &st); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if st.Stage != name {
		return nil, fmt.Errorf("%s: stage field %q does not match file name", path, st.Stage)
	}
	seen := map[string]bool{}
	for i, f := range st.Fixtures {
		if f.ID == "" || f.Category == "" || f.Input == nil {
			return nil, fmt.Errorf("%s: fixture %d needs id, category and input", path, i)
		}
		if seen[f.ID] {
			return nil, fmt.Errorf("%s: duplicate fixture id %q", path, f.ID)
		}
		seen[f.ID] = true
		st.Fixtures[i].Expect = st.Defaults.merge(f.Expect)
	}
	sort.SliceStable(st.Fixtures, func(i, j int) bool { return st.Fixtures[i].ID < st.Fixtures[j].ID })
	if st.MemoryFile != "" {
		mem, err := os.ReadFile(filepath.Join(dir, "stages", st.MemoryFile))
		if err != nil {
			return nil, err
		}
		st.memory = string(mem)
	}
	return &st, nil
}

func loadContestants(dir string) (map[string]Contestant, error) {
	raw, err := os.ReadFile(filepath.Join(dir, "contestants.yaml"))
	if err != nil {
		return nil, err
	}
	var file struct {
		Contestants []Contestant `yaml:"contestants"`
	}
	if err := yaml.Unmarshal(raw, &file); err != nil {
		return nil, err
	}
	out := map[string]Contestant{}
	for _, c := range file.Contestants {
		out[c.Name] = c
	}
	return out, nil
}
