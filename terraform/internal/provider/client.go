package provider

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strings"
	"time"
)

// Client is a thin HTTP client for the ProveKit control-plane routes.
//
// It authenticates with a *session cookie*, not a `pk_` project key, because the endpoints
// this provider drives (`/api/projects`, `/api/api-keys`, `/api/alerts`) are cookie-authed —
// see services/auth.py:get_current_user, which reads the `agm_session` cookie and has no
// bearer branch. A project key would 401 on every one of them. docs/TERRAFORM.md explains
// why that makes this provider unpublishable as-is.
type Client struct {
	BaseURL string
	HTTP    *http.Client
}

// NewClient builds a client with a cookie jar. The jar is what carries `agm_session` from
// the login call to every subsequent request; without it each request is anonymous.
func NewClient(baseURL string, timeout time.Duration) (*Client, error) {
	jar, err := cookiejar.New(nil)
	if err != nil {
		return nil, err
	}
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		HTTP:    &http.Client{Jar: jar, Timeout: timeout},
	}, nil
}

// APIError carries the status code so callers can branch on 404 (drift → remove from state)
// without string-matching the human-readable message, which docs/API_STABILITY.md explicitly
// declines to make part of the contract.
type APIError struct {
	Status int
	Method string
	Path   string
	Body   string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("%s %s: HTTP %d: %s", e.Method, e.Path, e.Status, e.Body)
}

// IsNotFound reports whether err is a 404, i.e. the object is gone server-side.
func IsNotFound(err error) bool {
	var apiErr *APIError
	return errors.As(err, &apiErr) && apiErr.Status == http.StatusNotFound
}

// Login exchanges credentials for a session cookie stored in the jar.
func (c *Client) Login(ctx context.Context, email, password string) error {
	body := map[string]string{"email": email, "password": password}
	return c.do(ctx, http.MethodPost, "/api/auth/login", "", body, nil)
}

// Me verifies the session is usable. Called after Login (and instead of it, in local mode
// where the server auto-provisions a user and no credentials are required) so a
// misconfigured provider fails at `terraform plan` with one clear message rather than at the
// first resource operation with three identical ones.
func (c *Client) Me(ctx context.Context) error {
	return c.do(ctx, http.MethodGet, "/api/auth/me", "", nil, nil)
}

// do issues one request. projectID, when non-empty, is sent as `X-Project-Id`: the header
// services/workspace.py:current_workspace uses to pick the tenant, and which it honors only
// if the session's user is a member of that project.
func (c *Client) do(ctx context.Context, method, path, projectID string, in, out any) error {
	var reader io.Reader
	if in != nil {
		buf, err := json.Marshal(in)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(buf)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, reader)
	if err != nil {
		return err
	}
	if in != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if projectID != "" {
		req.Header.Set("X-Project-Id", projectID)
	}

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return &APIError{Status: resp.StatusCode, Method: method, Path: path, Body: strings.TrimSpace(string(raw))}
	}
	if out == nil {
		return nil
	}
	return json.Unmarshal(raw, out)
}

// ---- projects (/api/projects) ----

// Project mirrors the object returned by GET /api/projects. Note that POST /api/projects
// returns a *narrower* object: it has no retention/redact_pii/replay_url, because those are
// settings the create route does not accept. Callers must re-read after create.
type Project struct {
	ID        int64  `json:"id"`
	Name      string `json:"name"`
	Role      string `json:"role"`
	Retention int64  `json:"retention"`
	RedactPII bool   `json:"redact_pii"`
	ReplayURL string `json:"replay_url"`
	CreatedAt string `json:"created_at"`
}

func (c *Client) CreateProject(ctx context.Context, name string) (*Project, error) {
	var p Project
	if err := c.do(ctx, http.MethodPost, "/api/projects", "", map[string]string{"name": name}, &p); err != nil {
		return nil, err
	}
	return &p, nil
}

// GetProject reads one project by id.
//
// There is no `GET /api/projects/{id}` route, so this lists and filters client-side. That is
// O(projects) per read and the honest consequence of driving a UI-shaped API: the listing is
// the only read path the server offers.
func (c *Client) GetProject(ctx context.Context, id string) (*Project, error) {
	var all []Project
	if err := c.do(ctx, http.MethodGet, "/api/projects", "", nil, &all); err != nil {
		return nil, err
	}
	for i := range all {
		if fmt.Sprint(all[i].ID) == id {
			return &all[i], nil
		}
	}
	return nil, &APIError{Status: http.StatusNotFound, Method: http.MethodGet, Path: "/api/projects",
		Body: "project " + id + " is not visible to this account"}
}

// ProjectPatch is PATCH /api/projects/{id}. Every field is a pointer because the server
// treats null as "leave alone" — sending a zero value would silently reset retention to 0
// (unlimited) or turn PII redaction off.
type ProjectPatch struct {
	Name      *string `json:"name,omitempty"`
	Retention *int64  `json:"retention,omitempty"`
	RedactPII *bool   `json:"redact_pii,omitempty"`
	ReplayURL *string `json:"replay_url,omitempty"`
}

func (c *Client) UpdateProject(ctx context.Context, id string, patch ProjectPatch) error {
	return c.do(ctx, http.MethodPatch, "/api/projects/"+url.PathEscape(id), "", patch, nil)
}

func (c *Client) DeleteProject(ctx context.Context, id string) error {
	return c.do(ctx, http.MethodDelete, "/api/projects/"+url.PathEscape(id), "", nil, nil)
}

// ---- api keys (/api/api-keys) ----

// APIKey mirrors routers/apikeys.py:_public. `Key` is populated on create only — the
// plaintext is shown once and only the SHA-256 hash is stored, so no later read can recover it.
type APIKey struct {
	ID         int64  `json:"id"`
	Name       string `json:"name"`
	Prefix     string `json:"prefix"`
	Revoked    bool   `json:"revoked"`
	LastUsedAt string `json:"last_used_at"`
	CreatedAt  string `json:"created_at"`
	Key        string `json:"key"`
}

func (c *Client) CreateAPIKey(ctx context.Context, projectID, name string) (*APIKey, error) {
	var k APIKey
	if err := c.do(ctx, http.MethodPost, "/api/api-keys", projectID, map[string]string{"name": name}, &k); err != nil {
		return nil, err
	}
	return &k, nil
}

// GetAPIKey reads one key by id, again by listing — there is no per-key GET route.
func (c *Client) GetAPIKey(ctx context.Context, projectID, id string) (*APIKey, error) {
	var all []APIKey
	if err := c.do(ctx, http.MethodGet, "/api/api-keys", projectID, nil, &all); err != nil {
		return nil, err
	}
	for i := range all {
		if fmt.Sprint(all[i].ID) == id {
			return &all[i], nil
		}
	}
	return nil, &APIError{Status: http.StatusNotFound, Method: http.MethodGet, Path: "/api/api-keys",
		Body: "api key " + id + " is not in project " + projectID}
}

// RevokeAPIKey is DELETE /api/api-keys/{id}. It is a *soft* delete: the row survives so
// last-used history does, and comes back from the listing with revoked=true.
func (c *Client) RevokeAPIKey(ctx context.Context, projectID, id string) error {
	return c.do(ctx, http.MethodDelete, "/api/api-keys/"+url.PathEscape(id), projectID, nil, nil)
}

// ---- alerts (/api/alerts) ----

// Alert mirrors routers/alerts.py:_row.
type Alert struct {
	ID              int64   `json:"id"`
	Name            string  `json:"name"`
	Metric          string  `json:"metric"`
	Comparator      string  `json:"comparator"`
	Threshold       float64 `json:"threshold"`
	WindowHours     int64   `json:"window_hours"`
	Email           string  `json:"email"`
	WebhookURL      string  `json:"webhook_url"`
	Enabled         bool    `json:"enabled"`
	LastTriggeredAt string  `json:"last_triggered_at"`
	CreatedAt       string  `json:"created_at"`
}

// AlertIn is the POST /api/alerts body.
type AlertIn struct {
	Name        string  `json:"name"`
	Metric      string  `json:"metric"`
	Comparator  string  `json:"comparator"`
	Threshold   float64 `json:"threshold"`
	WindowHours int64   `json:"window_hours"`
	Email       string  `json:"email"`
	WebhookURL  string  `json:"webhook_url"`
	Enabled     bool    `json:"enabled"`
}

func (c *Client) CreateAlert(ctx context.Context, projectID string, in AlertIn) (*Alert, error) {
	var a Alert
	if err := c.do(ctx, http.MethodPost, "/api/alerts", projectID, in, &a); err != nil {
		return nil, err
	}
	return &a, nil
}

func (c *Client) GetAlert(ctx context.Context, projectID, id string) (*Alert, error) {
	var all []Alert
	if err := c.do(ctx, http.MethodGet, "/api/alerts", projectID, nil, &all); err != nil {
		return nil, err
	}
	for i := range all {
		if fmt.Sprint(all[i].ID) == id {
			return &all[i], nil
		}
	}
	return nil, &APIError{Status: http.StatusNotFound, Method: http.MethodGet, Path: "/api/alerts",
		Body: "alert " + id + " is not in project " + projectID}
}

// SetAlertEnabled is the whole of PATCH /api/alerts/{id}: the route's body model
// (_AlertPatch) has exactly one field. Every other attribute of an alert is immutable
// server-side, which is why the resource marks them RequiresReplace.
func (c *Client) SetAlertEnabled(ctx context.Context, projectID, id string, enabled bool) error {
	return c.do(ctx, http.MethodPatch, "/api/alerts/"+url.PathEscape(id), projectID,
		map[string]bool{"enabled": enabled}, nil)
}

func (c *Client) DeleteAlert(ctx context.Context, projectID, id string) error {
	return c.do(ctx, http.MethodDelete, "/api/alerts/"+url.PathEscape(id), projectID, nil, nil)
}
