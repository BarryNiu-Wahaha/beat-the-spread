# Run once: powershell -NoProfile -File .\scripts\collect_odds_sample.ps1
# Requests only NBA / US / h2h odds. No loops, retries, or scheduled calls.
$ErrorActionPreference = 'Stop'
$apiKey = $env:ODDS_API_KEY
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    $secureKey = Read-Host 'The Odds API key (hidden)' -AsSecureString
    $apiKey = [System.Net.NetworkCredential]::new('', $secureKey).Password
}
if ([string]::IsNullOrWhiteSpace($apiKey)) { throw 'API key is required.' }

$started = [DateTime]::UtcNow
$until = $started.AddDays(3).ToString('yyyy-MM-ddTHH:mm:ssZ')
$endpoint = 'https://api.the-odds-api.com/v4/sports/basketball_nba/odds'
$uri = $endpoint + '?regions=us&markets=h2h&oddsFormat=decimal&dateFormat=iso&commenceTimeTo=' + $until
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root ('data\collected\odds_sample_' + $started.ToString('yyyyMMddTHHmmssfffffffZ'))
$null = New-Item -ItemType Directory -Path $output
$report = [ordered]@{
    source = 'The Odds API'; endpoint = $endpoint
    attempted_at_utc = $started.ToString('o'); request_attempts = 1
    regions = 'us'; markets = 'h2h'; commence_time_to_utc = $until
    automatic_retries = 0; expected_credits = 1; status = 'pending'
    credits_last = $null; credits_used = $null; credits_remaining = $null
}
try {
    $response = Invoke-WebRequest -Uri $uri -Headers @{'x-api-key' = $apiKey} -UseBasicParsing -TimeoutSec 25 -MaximumRedirection 0
    $report.credits_last = $response.Headers['x-requests-last']
    $report.credits_used = $response.Headers['x-requests-used']
    $report.credits_remaining = $response.Headers['x-requests-remaining']
    $response.Content | Set-Content -LiteralPath (Join-Path $output 'odds_raw.json') -Encoding UTF8
    # Windows PowerShell returns the JSON array as one pipeline object.
    # Assign it directly so foreach visits games rather than a nested array.
    $games = ConvertFrom-Json -InputObject $response.Content
    $retrieved = [DateTime]::UtcNow.ToString('o')
    $rows = @(foreach ($game in $games) {
        foreach ($bookmaker in $game.bookmakers) {
            foreach ($market in $bookmaker.markets) {
                foreach ($outcome in $market.outcomes) {
                    $updated = $market.last_update
                    if (-not $updated) { $updated = $bookmaker.last_update }
                    [pscustomobject]@{
                        event_id = $game.id; commence_time_utc = $game.commence_time
                        home_team = $game.home_team; away_team = $game.away_team
                        bookmaker = $bookmaker.key; market = $market.key
                        outcome = $outcome.name; decimal_odds = $outcome.price
                        source_updated_at_utc = $updated; retrieved_at_utc = $retrieved
                    }
                }
            }
        }
    })
    if ($rows.Count -gt 0) {
        $rows | Export-Csv -LiteralPath (Join-Path $output 'odds.csv') -NoTypeInformation -Encoding UTF8
    }
    $report.status = 'collected'
    $report.games = $games.Count
    $report.odds_rows = $rows.Count
} catch {
    $report.status = 'failed'
    $report.error = $_.Exception.Message
    Write-Warning 'Request or processing failed. No automatic retry. See collection_status.json.'
} finally {
    $apiKey = $null
    $secureKey = $null
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'collection_status.json') -Encoding UTF8
}
$report | ConvertTo-Json -Depth 5
Write-Output ('Saved to: ' + $output)
if ($report.status -ne 'collected') { exit 1 }
