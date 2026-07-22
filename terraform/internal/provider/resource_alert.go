package provider

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/float64default"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/float64planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/int64default"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/int64planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

var (
	_ resource.Resource                   = (*alertResource)(nil)
	_ resource.ResourceWithConfigure      = (*alertResource)(nil)
	_ resource.ResourceWithImportState    = (*alertResource)(nil)
	_ resource.ResourceWithValidateConfig = (*alertResource)(nil)
)

// alertMetrics and alertComparators mirror the server's allowlists in routers/alerts.py
// (`_METRICS`, `_COMPARATORS`). Duplicating them here buys a plan-time error instead of a
// 422 halfway through an apply; the cost is that a metric added server-side needs a matching
// change here, which is one more reason this provider wants a real versioned API.
var (
	alertMetrics = map[string]bool{
		"error_rate": true, "latency_p50_ms": true, "latency_p95_ms": true,
		"trace_count": true, "total_tokens": true, "error_count": true,
	}
	alertComparators = map[string]bool{"gt": true, "lt": true}
)

// NewAlertResource builds the provekit_alert resource.
func NewAlertResource() resource.Resource { return &alertResource{} }

type alertResource struct{ client *Client }

type alertModel struct {
	ID              types.String  `tfsdk:"id"`
	ProjectID       types.String  `tfsdk:"project_id"`
	Name            types.String  `tfsdk:"name"`
	Metric          types.String  `tfsdk:"metric"`
	Comparator      types.String  `tfsdk:"comparator"`
	Threshold       types.Float64 `tfsdk:"threshold"`
	WindowHours     types.Int64   `tfsdk:"window_hours"`
	Email           types.String  `tfsdk:"email"`
	WebhookURL      types.String  `tfsdk:"webhook_url"`
	Enabled         types.Bool    `tfsdk:"enabled"`
	LastTriggeredAt types.String  `tfsdk:"last_triggered_at"`
	CreatedAt       types.String  `tfsdk:"created_at"`
}

func (r *alertResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_alert"
}

func (r *alertResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A threshold rule over dashboard metrics. Maps to `/api/alerts`.\n\n" +
			"`enabled` is the only attribute that can be changed in place: the server's PATCH body " +
			"(`_AlertPatch`) has exactly one field. Everything else forces replacement.\n\n" +
			"Alerts are evaluated on demand by `POST /api/alerts/check`, not on a timer. Creating " +
			"one here does not schedule it — you still need a cron hitting that endpoint.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				MarkdownDescription: "Numeric alert id, as a string.",
				Computed:            true,
				PlanModifiers:       []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"project_id": schema.StringAttribute{
				MarkdownDescription: "Project the alert belongs to. Sent as `X-Project-Id`.",
				Required:            true,
				PlanModifiers:       []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"name": schema.StringAttribute{
				MarkdownDescription: "Rule name. Defaults to the metric name. Truncated to 160 " +
					"characters server-side.",
				Optional: true,
				Computed: true,
				// No static default: the server's fallback is the *metric*, which is not
				// knowable at schema-build time. UseStateForUnknown keeps the value the
				// server chose from re-planning as a diff on every run.
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
					stringplanmodifier.RequiresReplace(),
				},
			},
			"metric": schema.StringAttribute{
				MarkdownDescription: "Metric to watch: `error_rate`, `latency_p50_ms`, " +
					"`latency_p95_ms`, `trace_count`, `total_tokens` or `error_count`.",
				Required:      true,
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"comparator": schema.StringAttribute{
				MarkdownDescription: "`gt` to fire above the threshold, `lt` to fire below it.",
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString("gt"),
				PlanModifiers:       []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"threshold": schema.Float64Attribute{
				MarkdownDescription: "Value the metric is compared against.",
				Optional:            true,
				Computed:            true,
				Default:             float64default.StaticFloat64(0),
				PlanModifiers:       []planmodifier.Float64{float64planmodifier.RequiresReplace()},
			},
			"window_hours": schema.Int64Attribute{
				MarkdownDescription: "Lookback window, in hours. Also acts as the cooldown: a rule " +
					"will not fire again within its own window. Clamped to at least 1.",
				Optional:      true,
				Computed:      true,
				Default:       int64default.StaticInt64(24),
				PlanModifiers: []planmodifier.Int64{int64planmodifier.RequiresReplace()},
			},
			"email": schema.StringAttribute{
				MarkdownDescription: "Address notified on a breach. Truncated to 255 characters.",
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString(""),
				PlanModifiers:       []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"webhook_url": schema.StringAttribute{
				MarkdownDescription: "Webhook notified on a breach. The server runs its SSRF guard " +
					"(`services/netguard.guard_url`) on this value at create time and rejects a " +
					"private or malformed URL with a 422, so a bad hook fails the apply rather than " +
					"failing silently at 3am. Truncated to 500 characters.",
				Optional:      true,
				Computed:      true,
				Default:       stringdefault.StaticString(""),
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"enabled": schema.BoolAttribute{
				MarkdownDescription: "Whether the rule is evaluated. The only updatable attribute.",
				Optional:            true,
				Computed:            true,
				Default:             booldefault.StaticBool(true),
			},
			"last_triggered_at": schema.StringAttribute{
				MarkdownDescription: "RFC 3339 timestamp of the last time this rule fired, or null.",
				Computed:            true,
			},
			"created_at": schema.StringAttribute{
				MarkdownDescription: "RFC 3339 creation timestamp.",
				Computed:            true,
			},
		},
	}
}

func (r *alertResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFrom(req, resp)
}

// ValidateConfig rejects a metric or comparator the server will reject anyway, at plan time.
func (r *alertResource) ValidateConfig(ctx context.Context, req resource.ValidateConfigRequest, resp *resource.ValidateConfigResponse) {
	var cfg alertModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &cfg)...)
	if resp.Diagnostics.HasError() {
		return
	}
	if v := cfg.Metric; !v.IsNull() && !v.IsUnknown() && !alertMetrics[v.ValueString()] {
		resp.Diagnostics.AddAttributeError(path.Root("metric"), "Unsupported alert metric",
			fmt.Sprintf("%q is not a metric ProveKit can alert on. Supported: %s.",
				v.ValueString(), strings.Join(sortedKeys(alertMetrics), ", ")))
	}
	if v := cfg.Comparator; !v.IsNull() && !v.IsUnknown() && !alertComparators[v.ValueString()] {
		resp.Diagnostics.AddAttributeError(path.Root("comparator"), "Unsupported comparator",
			fmt.Sprintf("%q is not a comparator. Supported: %s.",
				v.ValueString(), strings.Join(sortedKeys(alertComparators), ", ")))
	}
}

func (r *alertResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan alertModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	created, err := r.client.CreateAlert(ctx, plan.ProjectID.ValueString(), AlertIn{
		Name:        plan.Name.ValueString(), // unknown → "" → server falls back to the metric
		Metric:      plan.Metric.ValueString(),
		Comparator:  plan.Comparator.ValueString(),
		Threshold:   plan.Threshold.ValueFloat64(),
		WindowHours: plan.WindowHours.ValueInt64(),
		Email:       plan.Email.ValueString(),
		WebhookURL:  plan.WebhookURL.ValueString(),
		Enabled:     plan.Enabled.ValueBool(),
	})
	if err != nil {
		resp.Diagnostics.AddError("Unable to create alert", err.Error())
		return
	}

	applyAlert(created, &plan)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *alertResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state alertModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	a, err := r.client.GetAlert(ctx, state.ProjectID.ValueString(), state.ID.ValueString())
	if err != nil {
		if IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		resp.Diagnostics.AddError("Unable to read alert", err.Error())
		return
	}
	applyAlert(a, &state)
	resp.Diagnostics.Append(resp.State.Set(ctx, &state)...)
}

func (r *alertResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state alertModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	plan.ID = state.ID

	// Only `enabled` reaches here; every other attribute is RequiresReplace.
	if err := r.client.SetAlertEnabled(ctx, plan.ProjectID.ValueString(), plan.ID.ValueString(),
		plan.Enabled.ValueBool()); err != nil {
		resp.Diagnostics.AddError("Unable to update alert", err.Error())
		return
	}

	a, err := r.client.GetAlert(ctx, plan.ProjectID.ValueString(), plan.ID.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Unable to read alert back after update", err.Error())
		return
	}
	applyAlert(a, &plan)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *alertResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state alertModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	if err := r.client.DeleteAlert(ctx, state.ProjectID.ValueString(), state.ID.ValueString()); err != nil && !IsNotFound(err) {
		resp.Diagnostics.AddError("Unable to delete alert", err.Error())
	}
}

// ImportState accepts "project_id:alert_id".
func (r *alertResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	projectID, id, ok := splitImportID(req.ID)
	if !ok {
		resp.Diagnostics.AddError(
			"Invalid import ID",
			"Expected \"project_id:alert_id\" (for example \"3:9\"), got: "+req.ID,
		)
		return
	}
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, path.Root("project_id"), projectID)...)
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, path.Root("id"), id)...)
}

func applyAlert(a *Alert, m *alertModel) {
	m.ID = types.StringValue(fmt.Sprint(a.ID))
	m.Name = types.StringValue(a.Name)
	m.Metric = types.StringValue(a.Metric)
	m.Comparator = types.StringValue(a.Comparator)
	m.Threshold = types.Float64Value(a.Threshold)
	m.WindowHours = types.Int64Value(a.WindowHours)
	m.Email = types.StringValue(a.Email)
	m.WebhookURL = types.StringValue(a.WebhookURL)
	m.Enabled = types.BoolValue(a.Enabled)
	m.LastTriggeredAt = optionalString(a.LastTriggeredAt)
	m.CreatedAt = types.StringValue(a.CreatedAt)
}

func sortedKeys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
