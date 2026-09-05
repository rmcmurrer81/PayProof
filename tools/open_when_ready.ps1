param(
    [string]$Url = "http://127.0.0.1:8765/api/health",
    [int]$TimeoutSeconds = 30
)

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $appUrl = $Url -replace '/api/health$', ''
            Start-Process $appUrl
            exit 0
        }
    }
    catch {
        Start-Sleep -Milliseconds 250
    }
}

exit 1
