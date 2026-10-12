package main

import (
	"bytes"
	"strings"
	"testing"
)

func ptr[T any](v T) *T { return &v }

func run(draft string, escalate *string) *RunResult {
	r := &RunResult{OK: true}
	r.Result.Draft = draft
	r.Result.Escalate = escalate
	return r
}

func checkNamed(checks []Check, name string) *Check {
	for i := range checks {
		if checks[i].Name == name {
			return &checks[i]
		}
	}
	return nil
}

func TestScoreEscalate(t *testing.T) {
	want := Expect{Escalate: ptr(true)}
	if !passed(score(run("ok", ptr("do work")), want)) {
		t.Fatal("escalation present should pass")
	}
	if passed(score(run("ok", nil), want)) {
		t.Fatal("missing escalation should fail")
	}
	if passed(score(run("ok", ptr("x")), Expect{Escalate: ptr(false)})) {
		t.Fatal("unexpected escalation should fail")
	}
}

func TestScoreTextChecks(t *testing.T) {
	ex := Expect{MaxChars: 10, ContainsAny: []string{"Llama"}, MustNotContain: []string{"sam"},
		MustNotMatch: []string{`here'?s (the|my) draft`}}
	if !passed(score(run("llama ok", nil), ex)) {
		t.Fatal("clean short draft should pass")
	}
	checks := score(run("Here's my draft: llama, Sam", nil), ex)
	for _, name := range []string{"max_chars", "must_not_contain", "must_not_match"} {
		if c := checkNamed(checks, name); c == nil || c.Passed {
			t.Fatalf("%s should fail: %+v", name, checks)
		}
	}
	if c := checkNamed(score(run("hi", nil), ex), "contains_any"); c == nil || c.Passed {
		t.Fatal("contains_any should fail without a match")
	}
}

func TestScoreRunFailureAndEmpty(t *testing.T) {
	if passed(score(&RunResult{OK: false, Error: "boom"}, Expect{})) {
		t.Fatal("failed run should fail")
	}
	if passed(score(nil, Expect{})) {
		t.Fatal("nil run should fail")
	}
	if c := checkNamed(score(run("  ", nil), Expect{}), "non_empty"); c == nil {
		t.Fatal("empty draft should add a failing non_empty check")
	}
}

func TestBadRegexFailsInsteadOfPanicking(t *testing.T) {
	if passed(score(run("x", nil), Expect{MustNotMatch: []string{"("}})) {
		t.Fatal("bad regex should fail the check")
	}
}

func TestMergeDefaults(t *testing.T) {
	d := Expect{MaxChars: 900, MustNotMatch: []string{"a"}}
	m := d.merge(Expect{Escalate: ptr(true), MustNotMatch: []string{"b"}})
	if m.MaxChars != 900 || *m.Escalate != true || len(m.MustNotMatch) != 2 {
		t.Fatalf("merge: %+v", m)
	}
	if len(d.MustNotMatch) != 1 {
		t.Fatal("merge must not mutate defaults")
	}
}

func TestReportFlagsHarnessErrors(t *testing.T) {
	st := &Stage{Stage: "s", Robot: "r"}
	cs := []Contestant{{Name: "mock", Role: "mock", Brain: "mock"}}
	ok := []Sample{{Contestant: "mock", Fixture: "f", Category: "c", Passed: true,
		Checks: []Check{{Name: "ran", Passed: true}}}}
	var buf bytes.Buffer
	if !report(&buf, st, cs, ok, 0) {
		t.Fatal("clean run should report ok")
	}
	broken := []Sample{{Contestant: "mock", Fixture: "f", Category: "c",
		Checks: []Check{{Name: "ran", Detail: "runner failed"}}}}
	buf.Reset()
	if report(&buf, st, cs, broken, 0) || !strings.Contains(buf.String(), "HARNESS ERRORS") {
		t.Fatal("harness errors must fail the report")
	}
	if report(&buf, st, cs, ok, 1.01) {
		t.Fatal("min-pass above the rate must fail")
	}
}

func TestFilterMatchesAnyTerm(t *testing.T) {
	f := Fixture{ID: "decision_build_v3", Category: "decision"}
	for filter, want := range map[string]bool{
		"": true, "decision": true, "work, decision": true, "build_v3": true, "chat,work": false,
	} {
		if matches(f, filter) != want {
			t.Errorf("matches(%q) = %v, want %v", filter, !want, want)
		}
	}
}

// The committed stages must load, meet the fixture floor, and make every fixture
// assert something beyond the stage defaults.
func TestCommittedStages(t *testing.T) {
	st, err := loadStage(".", "reply-draft")
	if err != nil {
		t.Fatal(err)
	}
	if len(st.Fixtures) < 30 {
		t.Fatalf("reply-draft has %d fixtures; the floor is 30", len(st.Fixtures))
	}
	if st.memory == "" {
		t.Fatal("reply-draft memory did not load")
	}
	for _, f := range st.Fixtures {
		own := f.Expect.Escalate != nil || len(f.Expect.ContainsAny) > 0 ||
			len(f.Expect.MustNotMatch) > len(st.Defaults.MustNotMatch)
		if !own {
			t.Errorf("%s asserts nothing beyond the defaults", f.ID)
		}
	}
	cs, err := loadContestants(".")
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"rock", "proto", "bass", "mock"} {
		if _, ok := cs[name]; !ok {
			t.Errorf("contestants.yaml is missing %s", name)
		}
	}
}
