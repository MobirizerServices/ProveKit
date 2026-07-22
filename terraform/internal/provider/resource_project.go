package provider

import (
	"context"
	"fmt"

	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

var (
	_ resource.Resource                = (*projectResource)(nil)
	_ resource.ResourceWithConfigure   = (*projectResource)(nil)
	_ resource.ResourceWithImportState = (*projectResource)(nil)
)

// NewProjectResource builds the provekit_project resource.
func NewProjectResource() resource.Resource { return &projectResource{} }

type projectResource struct{ client *Client }

type projectModel struct {
	ID        types.String `tfsdk:"id"`
	Name      types.String `tfsdk:"name"`
	Retention types.Int64  `tfsdk:"retention"`
	RedactPII types.Bool   `tfsdk:"redact_pii"`
	ReplayURL types.String `tfsdk:"replay_url"`
	CreatedAt types.String `tfsdk:"created_at"`
}

func (r *projectResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_project"
}

func (r *projectResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A ProveKit project (workspace): an isolated tenant with its own " +
			"traces, keys, datasets and members. Maps to `/api/projects`.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				MarkdownDescription: "Numeric project id, as a string. This is the value to pass " +
					"as `X-Project-Id` and to `project_id` on other resources.",
				Computed:      true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"name": schema.StringAttribute{
				MarkdownDescription: "Display name. The server truncates to 160 characters; a longer " +
					"value will fail the apply with a consistency error rather than be silently cut.",
				Required: true,
			},
			// The three settings below are Optional+Computed: the server owns a default for
			// each, so omitting one must mean "whatever the server chose", not "reset it".
			// The tradeoff is the standard one — removing the attribute from config later
			// keeps the last applied value instead of reverting it.
			"retention": schema.Int64Attribute{
				MarkdownDescription: "Span retention in days. `0` means keep forever.",
				Optional:            true,
				Computed:            true,
			},
			"redact_pii": schema.BoolAttribute{
				MarkdownDescription: "Mask PII in spans before they are stored.",
				Optional:            true,
				Computed:            true,
			},
			"replay_url": schema.StringAttribute{
				MarkdownDescription: "Target URL for replaying a trace against your own service. " +
					"Validated by the server's SSRF guard when replay runs, not at apply time.",
				Optional: true,
				Computed: true,
			},
			"created_at": schema.StringAttribute{
				MarkdownDescription: "RFC 3339 creation timestamp.",
				Computed:            true,
			},
		},
	}
}

func (r *projectResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFrom(req, resp)
}

func (r *projectResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan projectModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	created, err := r.client.CreateProject(ctx, plan.Name.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Unable to create project", err.Error())
		return
	}
	id := fmt.Sprint(created.ID)

	// POST /api/projects accepts only `name` (routers/projects.py:_ProjectIn), so the
	// settings need a second call.
	var patchErr error
	if patch, dirty := projectPatchFrom(plan); dirty {
		patchErr = r.client.UpdateProject(ctx, id, patch)
	}

	// Write state before reporting any error from here on. The project exists now: a Create
	// that returns an error with empty state leaves a real project that Terraform does not
	// know about, and the next apply makes a second one. Partial state plus a loud error is
	// the recoverable failure; a clean error is not.
	p, err := r.client.GetProject(ctx, id)
	if err != nil {
		applyProject(created, &plan) // narrower than a full read, but it carries the id
		resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
		resp.Diagnostics.AddError("Project created but could not be read back", err.Error())
		return
	}
	applyProject(p, &plan)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
	if patchErr != nil {
		resp.Diagnostics.AddError("Project created but its settings could not be applied", patchErr.Error())
	}
}

func (r *projectResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state projectModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	p, err := r.client.GetProject(ctx, state.ID.ValueString())
	if err != nil {
		if IsNotFound(err) {
			resp.State.RemoveResource(ctx) // deleted outside Terraform → plan a re-create
			return
		}
		resp.Diagnostics.AddError("Unable to read project", err.Error())
		return
	}
	applyProject(p, &state)
	resp.Diagnostics.Append(resp.State.Set(ctx, &state)...)
}

func (r *projectResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state projectModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	plan.ID = state.ID

	patch, _ := projectPatchFrom(plan)
	if err := r.client.UpdateProject(ctx, plan.ID.ValueString(), patch); err != nil {
		resp.Diagnostics.AddError("Unable to update project", err.Error())
		return
	}

	// PATCH returns a partial object (no created_at), so re-read rather than trusting it.
	p, err := r.client.GetProject(ctx, plan.ID.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Unable to read project back after update", err.Error())
		return
	}
	applyProject(p, &plan)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *projectResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state projectModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	// This is not a soft delete. routers/projects.py:delete_project removes every run,
	// dataset, experiment, feedback, alert and key in the project first. `terraform destroy`
	// on this resource destroys the trace history with it.
	if err := r.client.DeleteProject(ctx, state.ID.ValueString()); err != nil && !IsNotFound(err) {
		resp.Diagnostics.AddError("Unable to delete project", err.Error())
	}
}

func (r *projectResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}

func applyProject(p *Project, m *projectModel) {
	m.ID = types.StringValue(fmt.Sprint(p.ID))
	m.Name = types.StringValue(p.Name)
	m.Retention = types.Int64Value(p.Retention)
	m.RedactPII = types.BoolValue(p.RedactPII)
	m.ReplayURL = types.StringValue(p.ReplayURL)
	m.CreatedAt = types.StringValue(p.CreatedAt)
}

// projectPatchFrom builds a PATCH body from known, non-null plan values. `dirty` reports
// whether any setting was actually specified, so Create can skip a pointless second call.
func projectPatchFrom(m projectModel) (ProjectPatch, bool) {
	patch := ProjectPatch{}
	dirty := false
	if !m.Name.IsNull() && !m.Name.IsUnknown() {
		v := m.Name.ValueString()
		patch.Name = &v
	}
	if !m.Retention.IsNull() && !m.Retention.IsUnknown() {
		v := m.Retention.ValueInt64()
		patch.Retention = &v
		dirty = true
	}
	if !m.RedactPII.IsNull() && !m.RedactPII.IsUnknown() {
		v := m.RedactPII.ValueBool()
		patch.RedactPII = &v
		dirty = true
	}
	if !m.ReplayURL.IsNull() && !m.ReplayURL.IsUnknown() {
		v := m.ReplayURL.ValueString()
		patch.ReplayURL = &v
		dirty = true
	}
	return patch, dirty
}
