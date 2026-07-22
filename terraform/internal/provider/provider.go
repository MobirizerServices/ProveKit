// Package provider implements the ProveKit Terraform provider.
//
// Scope note, read this before extending anything here: the three resources below drive
// `/api/*` routes, which docs/API_STABILITY.md classifies as **Internal — "No promise at
// all; changes without notice"**. ProveKit's stable `/v1` surface has no control-plane
// endpoints at all (it is traces, datasets, experiments, share and export). So this provider
// cannot currently be built the way that document tells integrators to build. It is a
// working prototype and a concrete argument for a `/v1` control plane, not a shipped
// integration. docs/TERRAFORM.md states the same thing at length.
package provider

import (
	"context"
	"os"
	"time"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/provider"
	"github.com/hashicorp/terraform-plugin-framework/provider/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// Ensure the implementation satisfies the framework interface at compile time.
var _ provider.Provider = (*provekitProvider)(nil)

type provekitProvider struct {
	version string
}

// New returns the constructor providerserver.Serve expects.
func New(version string) func() provider.Provider {
	return func() provider.Provider {
		return &provekitProvider{version: version}
	}
}

type providerModel struct {
	Endpoint types.String `tfsdk:"endpoint"`
	Email    types.String `tfsdk:"email"`
	Password types.String `tfsdk:"password"`
}

func (p *provekitProvider) Metadata(_ context.Context, _ provider.MetadataRequest, resp *provider.MetadataResponse) {
	resp.TypeName = "provekit"
	resp.Version = p.version
}

func (p *provekitProvider) Schema(_ context.Context, _ provider.SchemaRequest, resp *provider.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Manage ProveKit projects, project keys and alerts declaratively. " +
			"**Prototype:** drives the internal `/api` surface, which carries no compatibility " +
			"promise. See `docs/TERRAFORM.md`.",
		Attributes: map[string]schema.Attribute{
			"endpoint": schema.StringAttribute{
				MarkdownDescription: "Base URL of the ProveKit instance, e.g. `http://localhost:8000`. " +
					"Falls back to the `PROVEKIT_ENDPOINT` environment variable.",
				Optional: true,
			},
			"email": schema.StringAttribute{
				MarkdownDescription: "Account email. Falls back to `PROVEKIT_EMAIL`. Omit on an " +
					"instance running with `HOSTED=false`, where the server requires no login.",
				Optional: true,
			},
			"password": schema.StringAttribute{
				MarkdownDescription: "Account password. Falls back to `PROVEKIT_PASSWORD`. " +
					"Prefer the environment variable: a password in a `.tf` file is a password in git.",
				Optional:  true,
				Sensitive: true,
			},
		},
	}
}

func (p *provekitProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp *provider.ConfigureResponse) {
	var cfg providerModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &cfg)...)
	if resp.Diagnostics.HasError() {
		return
	}

	// Unknown at plan time means the value comes from another resource that hasn't been
	// applied yet. Returning early (rather than erroring) lets Terraform re-run Configure
	// during apply with the resolved value.
	if cfg.Endpoint.IsUnknown() || cfg.Email.IsUnknown() || cfg.Password.IsUnknown() {
		return
	}

	endpoint := firstNonEmpty(cfg.Endpoint.ValueString(), os.Getenv("PROVEKIT_ENDPOINT"), "http://localhost:8000")
	email := firstNonEmpty(cfg.Email.ValueString(), os.Getenv("PROVEKIT_EMAIL"))
	password := firstNonEmpty(cfg.Password.ValueString(), os.Getenv("PROVEKIT_PASSWORD"))

	client, err := NewClient(endpoint, 30*time.Second)
	if err != nil {
		resp.Diagnostics.AddError("Unable to construct ProveKit client", err.Error())
		return
	}

	// Credentials are optional on purpose. With HOSTED=false the server hands every request
	// a local user (services/auth.py:get_current_user), so demanding a password would make
	// the provider unusable in exactly the single-machine setup people try it in first.
	if email != "" || password != "" {
		if email == "" || password == "" {
			resp.Diagnostics.AddError(
				"Incomplete ProveKit credentials",
				"Set both `email` and `password` (or PROVEKIT_EMAIL and PROVEKIT_PASSWORD), or neither.",
			)
			return
		}
		if err := client.Login(ctx, email, password); err != nil {
			resp.Diagnostics.AddError("ProveKit login failed", err.Error())
			return
		}
	}

	// One reachability check up front, so a wrong endpoint or an expired session is reported
	// once by the provider instead of once per resource.
	if err := client.Me(ctx); err != nil {
		resp.Diagnostics.AddError(
			"Cannot authenticate against ProveKit",
			"GET /api/auth/me failed against "+endpoint+".\n\n"+
				"If this instance runs with HOSTED=true, set `email`/`password` "+
				"(or PROVEKIT_EMAIL/PROVEKIT_PASSWORD).\n\nUnderlying error: "+err.Error(),
		)
		return
	}

	resp.ResourceData = client
	resp.DataSourceData = client
}

func (p *provekitProvider) Resources(_ context.Context) []func() resource.Resource {
	return []func() resource.Resource{
		NewProjectResource,
		NewAPIKeyResource,
		NewAlertResource,
	}
}

// DataSources: none yet. A `provekit_project` data source is the obvious next addition, but
// it would read the same internal listing route, so it waits on the same `/v1` work.
func (p *provekitProvider) DataSources(_ context.Context) []func() datasource.DataSource {
	return nil
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

// clientFrom pulls the configured client out of a resource Configure request. Returns nil
// when ProviderData is absent, which is normal: the framework calls Configure once with a
// nil ProviderData before the provider itself is configured.
func clientFrom(req resource.ConfigureRequest, resp *resource.ConfigureResponse) *Client {
	if req.ProviderData == nil {
		return nil
	}
	client, ok := req.ProviderData.(*Client)
	if !ok {
		resp.Diagnostics.AddError(
			"Unexpected provider data",
			"Expected *provider.Client. This is a bug in the ProveKit provider.",
		)
		return nil
	}
	return client
}
