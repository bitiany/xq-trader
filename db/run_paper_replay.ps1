$ErrorActionPreference = "Stop"
$BaseUrl = "http://127.0.0.1:8096"
$AccountId = 1
$Operator = "auto-replay"
$ApprovedBy = "auto-replay"

$tradeDates = @(
    "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
    "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12",
    "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18",
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
    "2026-06-29", "2026-06-30",
    "2026-07-01", "2026-07-02", "2026-07-03",
    "2026-07-06", "2026-07-07", "2026-07-08"
)

$results = @()
$totalSignals = 0
$totalPreOrders = 0
$totalApproved = 0
$totalSubmitted = 0
$totalFailed = 0

foreach ($d in $tradeDates) {
    Write-Host ""
    Write-Host "=========================================="
    Write-Host "Replay date: $d"
    Write-Host "=========================================="

    # Step 1: run decision workflow
    $bodyObj = @{
        signal_date    = $d
        lookback_days  = 120
        min_confidence = 0.0
        max_selected   = 20
    }
    $body = $bodyObj | ConvertTo-Json -Compress

    $signalsCount = 0
    $preOrdersCount = 0
    $preOrderIds = @()
    $err = ""

    try {
        $r = Invoke-WebRequest -Uri "$BaseUrl/api/v1/trading/accounts/$AccountId/decision-workflow/run" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 300 -UseBasicParsing -ErrorAction Stop
        $j = $r.Content | ConvertFrom-Json
        if ($j.code -ne 0) {
            $err = "code=$($j.code) msg=$($j.message)"
            Write-Host "  [FAIL] decision-workflow $err"
            $results += [PSCustomObject]@{ date = $d; signals = 0; pre_orders = 0; approved = 0; submitted = 0; failed = 1; error = $err }
            $totalFailed++
            continue
        }
        $signalsCount = $j.data.signals_count
        $preOrdersCount = $j.data.pre_orders_count
        if ($j.data.pre_orders) {
            $preOrderIds = @($j.data.pre_orders | ForEach-Object { $_.id })
        }
        Write-Host ("  signals={0} pre_orders={1} fusion={2} sizing={3}" -f $signalsCount, $preOrdersCount, $j.data.fusion_count, $j.data.sizing_count)
        $totalSignals += $signalsCount
        $totalPreOrders += $preOrdersCount
    } catch {
        $err = $_.Exception.Message
        Write-Host "  [FAIL] decision-workflow exception: $err"
        $results += [PSCustomObject]@{ date = $d; signals = 0; pre_orders = 0; approved = 0; submitted = 0; failed = 1; error = $err }
        $totalFailed++
        continue
    }

    # Step 2: batch approve
    $approvedCount = 0
    if ($preOrderIds.Count -gt 0) {
        $appObj = @{
            pre_order_ids = $preOrderIds
            approved       = $true
            approved_by    = $ApprovedBy
            comment        = "auto-replay $d"
        }
        $appBody = $appObj | ConvertTo-Json -Depth 5 -Compress
        try {
            $r = Invoke-WebRequest -Uri "$BaseUrl/api/v1/trading/approval/batch" -Method POST -Body $appBody -ContentType "application/json" -TimeoutSec 60 -UseBasicParsing -ErrorAction Stop
            $j = $r.Content | ConvertFrom-Json
            $approvedCount = $j.data.approved
            Write-Host ("  approved={0} rejected={1} skipped={2}" -f $j.data.approved, $j.data.rejected, $j.data.skipped)
            $totalApproved += $approvedCount
        } catch {
            $err = "approval: " + $_.Exception.Message
            Write-Host "  [FAIL] batch approval exception: $err"
            $results += [PSCustomObject]@{ date = $d; signals = $signalsCount; pre_orders = $preOrdersCount; approved = 0; submitted = 0; failed = 1; error = $err }
            $totalFailed++
            continue
        }
    }

    # Step 3: batch submit
    $submittedCount = 0
    if ($preOrderIds.Count -gt 0) {
        $subObj = @{
            pre_order_ids = $preOrderIds
            operator       = $Operator
        }
        $subBody = $subObj | ConvertTo-Json -Depth 5 -Compress
        try {
            $r = Invoke-WebRequest -Uri "$BaseUrl/api/v1/trading/pre-orders/submit/batch" -Method POST -Body $subBody -ContentType "application/json" -TimeoutSec 120 -UseBasicParsing -ErrorAction Stop
            $j = $r.Content | ConvertFrom-Json
            $submittedCount = $j.data.submitted
            $failedCnt = if ($j.data.failed -is [array]) { $j.data.failed.Count } else { $j.data.failed }
            Write-Host ("  submitted={0} failed_in_batch={1}" -f $submittedCount, $failedCnt)
            $totalSubmitted += $submittedCount
        } catch {
            $err = "submit: " + $_.Exception.Message
            Write-Host "  [FAIL] batch submit exception: $err"
            $results += [PSCustomObject]@{ date = $d; signals = $signalsCount; pre_orders = $preOrdersCount; approved = $approvedCount; submitted = 0; failed = 1; error = $err }
            $totalFailed++
            continue
        }
    }

    $results += [PSCustomObject]@{ date = $d; signals = $signalsCount; pre_orders = $preOrdersCount; approved = $approvedCount; submitted = $submittedCount; failed = 0; error = "" }
}

Write-Host ""
Write-Host "=========================================="
Write-Host "Summary"
Write-Host "=========================================="
Write-Host ("Total trade dates: {0}" -f $tradeDates.Count)
Write-Host ("Total signals: {0}" -f $totalSignals)
Write-Host ("Total pre_orders: {0}" -f $totalPreOrders)
Write-Host ("Total approved: {0}" -f $totalApproved)
Write-Host ("Total submitted: {0}" -f $totalSubmitted)
Write-Host ("Failed days: {0}" -f $totalFailed)
Write-Host ""
Write-Host "Daily details:"
$results | Format-Table -AutoSize
$results | Export-Csv -Path "d:\ProgramData\xq-trader\replay_results.csv" -NoTypeInformation -Encoding UTF8
Write-Host "Results exported to: d:\ProgramData\xq-trader\replay_results.csv"
