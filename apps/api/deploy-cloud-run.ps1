param(
    [string]$ServiceName = "bidfinder-api",
    [string]$Region = "asia-southeast1",
    [string]$Memory = "512Mi",
    [string]$Cpu = "1",
    [int]$Concurrency = 10,
    [int]$MinInstances = 0,
    [int]$MaxInstances = 2,
    [string]$Timeout = "120s",
    [string]$DbSecretName = "bidfinder-neon-database-url",
    [string]$FrontendUrl = "https://bidfinder.vn",
    [string]$AllowedOrigins = "https://bidfinder.vn,https://www.bidfinder.vn,https://bidfinder.netlify.app,http://localhost:3000,http://127.0.0.1:3000",
    [int]$QueryRateLimitPerMinute = 2000,
    [int]$AutocompleteRateLimitPerMinute = 3000,
    [int]$PreviewRateLimitPerMinute = 3000,
    [int]$FilterConfigRateLimitPerMinute = 1000,
    [int]$AuthRateLimitPerMinute = 500
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

gcloud run deploy $ServiceName `
    --source $scriptDir `
    --region $Region `
    --allow-unauthenticated `
    --memory $Memory `
    --cpu $Cpu `
    --concurrency $Concurrency `
    --min-instances $MinInstances `
    --max-instances $MaxInstances `
    --timeout $Timeout `
    --set-secrets "DATABASE_URL=$DbSecretName`:latest" `
    --update-env-vars "^|^ENV=production|DB_POOL_MAX_SIZE=4|TRUST_PROXY_HEADERS=true|FRONTEND_URL=$FrontendUrl|ALLOWED_ORIGINS=$AllowedOrigins|QUERY_RATE_LIMIT_PER_MINUTE=$QueryRateLimitPerMinute|AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE=$AutocompleteRateLimitPerMinute|PREVIEW_RATE_LIMIT_PER_MINUTE=$PreviewRateLimitPerMinute|FILTER_CONFIG_RATE_LIMIT_PER_MINUTE=$FilterConfigRateLimitPerMinute|AUTH_RATE_LIMIT_PER_MINUTE=$AuthRateLimitPerMinute"
