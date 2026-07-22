package provider

import (
	"context"
	"fmt"
	"strings"

	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

var (
	_ resource.Resource                = (*apiKeyResource)(nil)
	_ resource.ResourceWithConfigure   = (*apiKeyResource)(nil)
	_ resource.ResourceWithImportState = (*apiKeyResource)(nil)
)

// NewAPIKeyResource builds the provekit_api_key resource.
func NewAPIKeyResource() resource.Resource { return &apiKeyResource{} }

type apiKeyResource struct{ client *Client }

type apiKeyModel struct {
	ID         types.String `tfsdk:"id"`
	ProjectID  types.String `tfsdk:"project_id"`
	Name       types.String `tfsdk:"name"`
	Key        types.String `tfsdk:"key"`
	Prefix     types.String `tfsdk:"prefix"`
	Revoked    types.Bool   `tfsdk:"revoked"`
	LastUsedAt types.String `tfsdk:"last_used_at"`
	CreatedAt  types.String `tfsdk:"created_at"`
}

func (r *apiKeyResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_api_key"
}

func (r *apiKeyResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A `pk_` project key for machine access (trace ingest, CI). Maps to " +
			"`/api/api-keys`.\n\n" +
			"Every attribute forces replacement because the server exposes no update route for a " +
			"key — create and revoke are the only verbs.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				MarkdownDescription: "Numeric key id, as a string.",
				Computed:            true,
				PlanModifiers:       []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"project_id": schema.StringAttribute{
				MarkdownDescription: "Project the key belongs to. Sent as `X-Project-Id`; the server " +
					"honors it only if the authenticated account is a member of that project.",
				Required:      true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"name": schema.StringAttribute{
				MarkdownDescription: "Label shown in the portal. Renaming replaces the key, because " +
					"the API has no way to rename one.",
				Optional:      true,
				Computed:      true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"key": schema.StringAttribute{
				MarkdownDescription: "The plaintext `pk_...` key. **Returned by the API exactly once, " +
					"at creation** — only its SHA-256 hash is stored server-side. It therefore lives " +
					"in Terraform state and nowhere else: treat the state file as a secret, and note " +
					"that an imported key has this attribute null forever.",
				Computed:      true,
				Sensitive:     true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"prefix": schema.StringAttribute{
				MarkdownDescription: "Display prefix of the key, safe to log.",
				Computed:            true,
			},
			"revoked": schema.BoolAttribute{
				MarkdownDescription: "Whether the key has been revoked.",
				Computed:            true,
			},
			"last_used_at": schema.StringAttribute{
				MarkdownDescription: "RFC 3339 timestamp of last use, or null if never used.",
				Computed:            true,
			},
			"created_at": schema.StringAttribute{
				MarkdownDescription: "RFC 3339 creation timestamp.",
				Computed:            true,
			},
		},
	}
}

func (r *apiKeyResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFrom(req, resp)
}

func (r *apiKeyResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan apiKeyModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	created, err := r.client.CreateAPIKey(ctx, plan.ProjectID.ValueString(), plan.Name.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Unable to create API key", err.Error())
		return
	}

	// The create response is the only place the plaintext ever appears, so state is written
	// straight from it. Re-reading here would be worse than useless: the listing does not
	// carry `key`, and we would overwrite the one copy that exists with null.
	applyAPIKey(created, &plan)
	plan.Key = types.StringValue(created.Key)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *apiKeyResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state apiKeyModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	k, err := r.client.GetAPIKey(ctx, state.ProjectID.ValueString(), state.ID.ValueString())
	if err != nil {
		if IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		resp.Diagnostics.AddError("Unable to read API key", err.Error())
		return
	}

	// A revoked key is treated as gone. Revocation is a soft delete server-side (the row
	// stays so last-used history survives), but a revoked key authenticates nothing, so
	// leaving it in state would let Terraform report "no changes" for a project whose ingest
	// is dead. Removing it plans a replacement, which is what the operator wants.
	if k.Revoked {
		resp.State.RemoveResource(ctx)
		return
	}

	applyAPIKey(k, &state) // deliberately does not touch Key — the API cannot return it again
	resp.Diagnostics.Append(resp.State.Set(ctx, &state)...)
}

// Update is unreachable: every configurable attribute is RequiresReplace and the rest are
// computed. Erroring rather than no-oping means that if a future schema change makes it
// reachable, we find out instead of silently writing a state that never hit the server.
func (r *apiKeyResource) Update(_ context.Context, _ resource.UpdateRequest, resp *resource.UpdateResponse) {
	resp.Diagnostics.AddError(
		"provekit_api_key cannot be updated in place",
		"The ProveKit API has no update route for a key. Every attribute of this resource is "+
			"marked RequiresReplace, so reaching Update is a bug in the provider.",
	)
}

func (r *apiKeyResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state apiKeyModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	// Revocation, not deletion: the row remains with revoked=true. The key stops working,
	// which is the property `terraform destroy` is being asked for, but the audit trail of
	// when it was last used stays readable in the portal.
	if err := r.client.RevokeAPIKey(ctx, state.ProjectID.ValueString(), state.ID.ValueString()); err != nil && !IsNotFound(err) {
		resp.Diagnostics.AddError("Unable to revoke API key", err.Error())
	}
}

// ImportState accepts "project_id:key_id" — the project is not derivable from the key id,
// because reading a key requires knowing which tenant to ask.
func (r *apiKeyResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	projectID, id, ok := splitImportID(req.ID)
	if !ok {
		resp.Diagnostics.AddError(
			"Invalid import ID",
			"Expected \"project_id:key_id\" (for example \"3:17\"), got: "+req.ID,
		)
		return
	}
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, path.Root("project_id"), projectID)...)
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, path.Root("id"), id)...)
	// `key` stays null: the plaintext is unrecoverable by design. An imported key is usable
	// as a managed object but its value can never be read back out of Terraform.
}

func applyAPIKey(k *APIKey, m *apiKeyModel) {
	m.ID = types.StringValue(fmt.Sprint(k.ID))
	m.Name = types.StringValue(k.Name)
	m.Prefix = types.StringValue(k.Prefix)
	m.Revoked = types.BoolValue(k.Revoked)
	m.LastUsedAt = optionalString(k.LastUsedAt)
	m.CreatedAt = types.StringValue(k.CreatedAt)
}

// optionalString maps the API's null timestamps to a null Terraform value rather than "",
// so `last_used_at == null` in HCL means what it says.
func optionalString(s string) types.String {
	if s == "" {
		return types.StringNull()
	}
	return types.StringValue(s)
}

func splitImportID(raw string) (projectID, id string, ok bool) {
	parts := strings.SplitN(raw, ":", 2)
	if len(parts) != 2 || strings.TrimSpace(parts[0]) == "" || strings.TrimSpace(parts[1]) == "" {
		return "", "", false
	}
	return strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1]), true
}
