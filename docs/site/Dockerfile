# The public docs site: build the MkDocs static HTML, then serve it from nginx.
#
# Two stages so the runtime image carries nothing but the rendered site — no Python, no build
# tools, ~40 MB of nginx + static files. The build is `--strict`, so a broken link or a missing
# nav target fails the image build rather than shipping a broken docs site.
#
# Built from the REPO ROOT (context: .) because mkdocs.yml uses `docs_dir: ..` — it renders the
# markdown that lives in docs/, which is the same content readable on GitHub. One source, two
# surfaces.

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir "mkdocs-material>=9,<10"
WORKDIR /w
COPY docs/ ./docs/
# -d /site overrides mkdocs.yml's site_dir (which points into the repo's gitignored build/).
RUN mkdocs build --strict -f docs/site/mkdocs.yml -d /site

FROM nginx:alpine
COPY --from=build /site /usr/share/nginx/html
COPY docs/site/nginx.conf /etc/nginx/conf.d/default.conf
