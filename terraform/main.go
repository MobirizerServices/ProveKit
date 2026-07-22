// Command terraform-provider-provekit serves the ProveKit Terraform provider over
// go-plugin. Terraform execs this binary; it does not run standalone.
package main

import (
	"context"
	"flag"
	"log"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"

	"github.com/provekit/terraform-provider-provekit/internal/provider"
)

// Overridden at release time with -ldflags "-X main.version=x.y.z". It is reported to
// Terraform in the provider metadata and is the only thing that tells a bug report which
// build produced it.
var version = "dev"

func main() {
	var debug bool
	flag.BoolVar(&debug, "debug", false, "run the provider with support for debuggers like delve")
	flag.Parse()

	// The address is the registry source address Terraform resolves in `required_providers`.
	// It must match the dev_overrides key in README.md or a local build will be ignored
	// silently — Terraform falls back to the registry rather than erroring.
	err := providerserver.Serve(context.Background(), provider.New(version), providerserver.ServeOpts{
		Address: "registry.terraform.io/provekit/provekit",
		Debug:   debug,
	})
	if err != nil {
		log.Fatal(err)
	}
}
