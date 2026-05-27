param(
    [string]$ServiceName = "bidfinder-api",
    [string]$Region = "asia-southeast1",
    [string]$Memory = "1Gi",
    [string]$Cpu = "1",
    [int]$Concurrency = 10,
    [int]$MinInstances = 0,
    [int]$MaxInstances = 6,
    [string]$Timeout = "120s",
    [int]$DbPoolMinSize = 0,
    [int]$DbPoolMaxSize = 4,
    [int]$DbPoolMaxInactiveConnectionLifetime = 30,
    [string]$DbSecretName = "bidfinder-neon-database-url",
    [string]$GoogleClientIdSecretName = "",
    [string]$ResendApiKeySecretName = "",
    [string]$ResendFromEmailSecretName = "",
    [string]$SmtpUsernameSecretName = "",
    [string]$SmtpPasswordSecretName = "",
    [string]$SmtpFromEmailSecretName = "",
    [string]$FrontendUrl = "https://bidfinder.vn",
    [string]$AllowedOrigins = "https://bidfinder.vn,https://www.bidfinder.vn,https://bidfinder.netlify.app,http://localhost:3000,http://127.0.0.1:3000",
    [string]$AppTimezone = "Asia/Ho_Chi_Minh",
    [string]$AnonymousAccessLevel = "full",
    [int]$AnonymousFullQueryDailyLimit = 5,
    [int]$FullSearchDailyLimit = 3,
    [string]$SmtpHost = "",
    [int]$SmtpPort = 587,
    [string]$SmtpFromName = "BIDFinder",
    [string]$SmtpUseTls = "true",
    [string]$SmtpUseSsl = "false",
    [string]$ResendFromName = "BIDFinder",
    [string]$AdminEmails = "admin@bidfinder.vn",
    [int]$QueryRateLimitPerMinute = 10000,
    [int]$AutocompleteRateLimitPerMinute = 10000,
    [int]$PreviewRateLimitPerMinute = 10000,
    [int]$FilterConfigRateLimitPerMinute = 1000,
    [int]$AuthRateLimitPerMinute = 500,
    [int]$FeedbackRateLimitPerMinute = 10000,
    [int]$FeedbackReadRateLimitPerMinute = 60
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envVars = @(
    "ENV=production",
    "ANONYMOUS_ACCESS_LEVEL=$AnonymousAccessLevel",
    "ANONYMOUS_FULL_QUERY_DAILY_LIMIT=$AnonymousFullQueryDailyLimit",
    "APP_FRONTEND_URL=$FrontendUrl",
    "APP_TIMEZONE=$AppTimezone",
    "AUTH_PASSWORD_RESET_URL_BASE=$FrontendUrl",
    "AUTH_SESSION_TOUCH_INTERVAL_SECONDS=300",
    "DB_POOL_MIN_SIZE=$DbPoolMinSize",
    "DB_POOL_MAX_SIZE=$DbPoolMaxSize",
    "DB_POOL_MAX_INACTIVE_CONNECTION_LIFETIME=$DbPoolMaxInactiveConnectionLifetime",
    "FULL_SEARCH_DAILY_LIMIT=$FullSearchDailyLimit",
    "TRUST_PROXY_HEADERS=true",
    "FRONTEND_URL=$FrontendUrl",
    "ALLOWED_ORIGINS=$AllowedOrigins",
    "QUERY_RATE_LIMIT_PER_MINUTE=$QueryRateLimitPerMinute",
    "AUTOCOMPLETE_RATE_LIMIT_PER_MINUTE=$AutocompleteRateLimitPerMinute",
    "PREVIEW_RATE_LIMIT_PER_MINUTE=$PreviewRateLimitPerMinute",
    "FILTER_CONFIG_RATE_LIMIT_PER_MINUTE=$FilterConfigRateLimitPerMinute",
    "AUTH_RATE_LIMIT_PER_MINUTE=$AuthRateLimitPerMinute",
    "FEEDBACK_RATE_LIMIT_PER_MINUTE=$FeedbackRateLimitPerMinute",
    "FEEDBACK_READ_RATE_LIMIT_PER_MINUTE=$FeedbackReadRateLimitPerMinute",
    "ADMIN_EMAILS=$AdminEmails",
    "RESEND_FROM_NAME=$ResendFromName"
)

if ($SmtpHost -or $SmtpUsernameSecretName -or $SmtpPasswordSecretName -or $SmtpFromEmailSecretName) {
    $envVars += @(
        "AUTH_SMTP_HOST=$SmtpHost",
        "AUTH_SMTP_PORT=$SmtpPort",
        "AUTH_SMTP_FROM_NAME=$SmtpFromName",
        "AUTH_SMTP_USE_TLS=$SmtpUseTls",
        "AUTH_SMTP_USE_SSL=$SmtpUseSsl"
    )
}
$envVarsArg = "^|^" + ($envVars -join "|")
$secrets = @("DATABASE_URL=$DbSecretName`:latest")

if ($GoogleClientIdSecretName) {
    $secrets += "GOOGLE_CLIENT_ID=$GoogleClientIdSecretName`:latest"
}
if ($ResendApiKeySecretName) {
    $secrets += "RESEND_API_KEY=$ResendApiKeySecretName`:latest"
}
if ($ResendFromEmailSecretName) {
    $secrets += "RESEND_FROM_EMAIL=$ResendFromEmailSecretName`:latest"
}
if ($SmtpUsernameSecretName) {
    $secrets += "AUTH_SMTP_USERNAME=$SmtpUsernameSecretName`:latest"
}
if ($SmtpPasswordSecretName) {
    $secrets += "AUTH_SMTP_PASSWORD=$SmtpPasswordSecretName`:latest"
}
if ($SmtpFromEmailSecretName) {
    $secrets += "AUTH_SMTP_FROM_EMAIL=$SmtpFromEmailSecretName`:latest"
}
$secretsArg = $secrets -join ","

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
    --update-secrets $secretsArg `
    --update-env-vars $envVarsArg
