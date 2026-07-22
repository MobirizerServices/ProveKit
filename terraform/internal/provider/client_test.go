package provider

import (
	"net/http"
	"testing"
)

func TestSplitImportID(t *testing.T) {
	cases := []struct {
		in          string
		wantProject string
		wantID      string
		wantOK      bool
	}{
		{"3:17", "3", "17", true},
		{" 3 : 17 ", "3", "17", true},
		{"3", "", "", false},
		{":17", "", "", false},
		{"3:", "", "", false},
		{"", "", "", false},
	}
	for _, c := range cases {
		project, id, ok := splitImportID(c.in)
		if ok != c.wantOK || project != c.wantProject || id != c.wantID {
			t.Errorf("splitImportID(%q) = (%q, %q, %v), want (%q, %q, %v)",
				c.in, project, id, ok, c.wantProject, c.wantID, c.wantOK)
		}
	}
}

func TestIsNotFound(t *testing.T) {
	if !IsNotFound(&APIError{Status: http.StatusNotFound}) {
		t.Error("404 should be reported as not found")
	}
	if IsNotFound(&APIError{Status: http.StatusForbidden}) {
		t.Error("403 is an authorization failure, not a missing object")
	}
	if IsNotFound(nil) {
		t.Error("nil error is not a missing object")
	}
}

func TestOptionalString(t *testing.T) {
	// The API returns null timestamps as JSON null, which decodes to "". Those must become
	// a null Terraform value, not the empty string, or `last_used_at != null` lies.
	if !optionalString("").IsNull() {
		t.Error("empty string should map to a null Terraform value")
	}
	if got := optionalString("2026-07-22T00:00:00Z").ValueString(); got != "2026-07-22T00:00:00Z" {
		t.Errorf("got %q, want the timestamp unchanged", got)
	}
}
