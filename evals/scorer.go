package main

import (
	"fmt"
	"regexp"
	"strings"
)

// Check is one named assertion outcome.
type Check struct {
	Name   string `json:"name"`
	Passed bool   `json:"passed"`
	Detail string `json:"detail,omitempty"`
}

func passed(checks []Check) bool {
	for _, c := range checks {
		if !c.Passed {
			return false
		}
	}
	return len(checks) > 0
}

// score checks one sample against its fixture's expectations. Deterministic only:
// anything code can check is checked here, never by a judge model.
func score(run *RunResult, ex Expect) []Check {
	if run == nil || !run.OK {
		detail := "no result"
		if run != nil {
			detail = run.Error
		}
		return []Check{{Name: "ran", Detail: detail}}
	}
	draft := run.Result.Draft
	checks := []Check{{Name: "ran", Passed: true}}

	if ex.Escalate != nil {
		got := run.Result.Escalate != nil && *run.Result.Escalate != ""
		checks = append(checks, Check{
			Name: "escalate", Passed: got == *ex.Escalate,
			Detail: fmt.Sprintf("want %v, got %v", *ex.Escalate, got),
		})
	}
	if strings.TrimSpace(draft) == "" {
		checks = append(checks, Check{Name: "non_empty", Detail: "empty draft"})
	}
	if ex.MaxChars > 0 {
		checks = append(checks, Check{
			Name: "max_chars", Passed: len(draft) <= ex.MaxChars,
			Detail: fmt.Sprintf("%d > %d", len(draft), ex.MaxChars),
		})
	}
	lower := strings.ToLower(draft)
	if len(ex.ContainsAny) > 0 {
		hit := false
		for _, n := range ex.ContainsAny {
			if strings.Contains(lower, strings.ToLower(n)) {
				hit = true
				break
			}
		}
		checks = append(checks, Check{Name: "contains_any", Passed: hit,
			Detail: fmt.Sprintf("none of %v", ex.ContainsAny)})
	}
	for _, n := range ex.MustNotContain {
		checks = append(checks, Check{Name: "must_not_contain",
			Passed: !strings.Contains(lower, strings.ToLower(n)), Detail: n})
	}
	for _, pat := range ex.MustNotMatch {
		re, err := regexp.Compile("(?i)" + pat)
		if err != nil {
			checks = append(checks, Check{Name: "must_not_match", Detail: "bad regex " + pat})
			continue
		}
		m := re.FindString(draft)
		checks = append(checks, Check{Name: "must_not_match", Passed: m == "", Detail: m})
	}
	return checks
}

// failures summarises the failed checks for the report.
func failures(checks []Check) string {
	var out []string
	for _, c := range checks {
		if !c.Passed {
			out = append(out, c.Name+": "+c.Detail)
		}
	}
	return strings.Join(out, "; ")
}
