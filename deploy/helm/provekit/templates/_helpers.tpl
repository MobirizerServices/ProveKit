{{/*
Name helpers.
*/}}
{{- define "provekit.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "provekit.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "provekit.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "provekit.labels" -}}
helm.sh/chart: {{ include "provekit.chart" . }}
app.kubernetes.io/name: {{ include "provekit.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: provekit
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Per-component selector labels. Call as (dict "ctx" . "component" "backend").
Selectors are immutable on a Deployment, so keep these minimal and stable.
*/}}
{{- define "provekit.selectorLabels" -}}
app.kubernetes.io/name: {{ include "provekit.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "provekit.componentLabels" -}}
{{ include "provekit.labels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
Image reference. Call as (include "provekit.image" (list . .Values.backend.image)).
*/}}
{{- define "provekit.image" -}}
{{- $ctx := index . 0 -}}
{{- $img := index . 1 -}}
{{- $tag := $img.tag | default $ctx.Chart.AppVersion -}}
{{- if $ctx.Values.imageRegistry -}}
{{- printf "%s/%s:%s" (trimSuffix "/" $ctx.Values.imageRegistry) $img.repository $tag -}}
{{- else -}}
{{- printf "%s:%s" $img.repository $tag -}}
{{- end -}}
{{- end -}}

{{/*
Object names.
*/}}
{{- define "provekit.backend.fullname" -}}
{{- printf "%s-backend" (include "provekit.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "provekit.frontend.fullname" -}}
{{- printf "%s-frontend" (include "provekit.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
The backend Service name. Overridable so the stock frontend image's build-time
API_PROXY_TARGET (http://backend:8000) resolves without a rebuild.
*/}}
{{- define "provekit.backend.serviceName" -}}
{{- default (include "provekit.backend.fullname" .) .Values.backend.service.name -}}
{{- end -}}

{{- define "provekit.postgresql.fullname" -}}
{{- printf "%s-postgresql" (include "provekit.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "provekit.redis.fullname" -}}
{{- printf "%s-redis" (include "provekit.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "provekit.configMapName" -}}
{{- printf "%s-config" (include "provekit.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "provekit.secretName" -}}
{{- default (printf "%s-secrets" (include "provekit.fullname" .)) .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "provekit.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "provekit.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Derived config.
*/}}
{{- define "provekit.baseUrl" -}}
{{- if .Values.config.domain -}}
{{- printf "https://%s" .Values.config.domain -}}
{{- else -}}
{{- printf "http://localhost:3000" -}}
{{- end -}}
{{- end -}}

{{- define "provekit.corsOrigins" -}}
{{- default (include "provekit.baseUrl" .) .Values.config.corsOrigins -}}
{{- end -}}

{{- define "provekit.webBaseUrl" -}}
{{- default (include "provekit.baseUrl" .) .Values.config.webBaseUrl -}}
{{- end -}}

{{- define "provekit.siteUrl" -}}
{{- default (include "provekit.baseUrl" .) .Values.config.siteUrl -}}
{{- end -}}

{{/*
DATABASE_URL: explicit value wins, else the bundled Postgres.
*/}}
{{- define "provekit.databaseUrl" -}}
{{- if .Values.secrets.databaseUrl -}}
{{- .Values.secrets.databaseUrl -}}
{{- else if .Values.postgresql.enabled -}}
{{- printf "postgresql+psycopg://%s:%s@%s:%v/%s" .Values.postgresql.auth.username (required "postgresql.auth.password is required when postgresql.enabled=true and secrets.databaseUrl is unset" .Values.postgresql.auth.password) (include "provekit.postgresql.fullname" .) .Values.postgresql.service.port .Values.postgresql.auth.database -}}
{{- else -}}
{{- fail "Set secrets.databaseUrl, or enable the bundled Postgres with postgresql.enabled=true" -}}
{{- end -}}
{{- end -}}

{{/*
REDIS_URL: explicit value wins, else the bundled Redis, else empty (in-memory limiters).
*/}}
{{- define "provekit.redisUrl" -}}
{{- if .Values.secrets.redisUrl -}}
{{- .Values.secrets.redisUrl -}}
{{- else if .Values.redis.enabled -}}
{{- printf "redis://%s:%v/0" (include "provekit.redis.fullname" .) .Values.redis.service.port -}}
{{- end -}}
{{- end -}}

{{- define "provekit.ingressHost" -}}
{{- default .Values.config.domain .Values.ingress.host -}}
{{- end -}}

{{/*
envFrom shared by both deployments: config first, secrets second so a secret key wins.
*/}}
{{- define "provekit.envFrom" -}}
- configMapRef:
    name: {{ include "provekit.configMapName" . }}
- secretRef:
    name: {{ include "provekit.secretName" . }}
{{- end -}}
