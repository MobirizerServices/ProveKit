module github.com/provekit/terraform-provider-provekit

go 1.21

// Only the direct dependency is pinned here. terraform-plugin-framework pulls in
// terraform-plugin-go, go-hclog, grpc and friends; run `go mod tidy` to write the indirect
// block and go.sum. No go.sum is committed because it has never been generated — see the
// "Unverified" note in README.md.
require github.com/hashicorp/terraform-plugin-framework v1.13.0
