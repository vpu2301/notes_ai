{{- define "notes.labels" -}}
app.kubernetes.io/part-of: notes
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "notes.image" -}}
{{- if .root.Values.global.imageRegistry -}}
{{ .root.Values.global.imageRegistry }}/{{ .image }}
{{- else -}}
{{ .image }}
{{- end -}}
{{- end -}}
