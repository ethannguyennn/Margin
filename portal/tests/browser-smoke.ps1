param([string]$Browse = (Join-Path $env:USERPROFILE '.agents/skills/gstack/browse/dist/browse.exe'))
# Run from the repository root with npm run dev:fixture active on :5177.
# Every route and credential below belongs to the local test fixture.
$steps = @'
[
 ["goto", "http://127.0.0.1:5177/portal/"],
 ["fill", "input[name=token]", "fixture-token"],
 ["click", "form.login button"],
 ["wait", "form.upload"],
 ["fill", "input[name=doc_id]", "SOP-150"],
 ["fill", "input[name=title]", "Synthetic pump seal swap"],
 ["upload", "input[name=file]", "__FILE__"],
 ["click", "form.upload button"],
 ["wait", "article"],
 ["is", "disabled", ".approval button"],
 ["fill", "input[name=glance]", "Torque to 4 N-m"],
 ["fill", "textarea[name=body]", "Torque the gland nut to 4 N-m."],
 ["click", "article form button"],
 ["wait", "article > p.pass"],
 ["click", "button:has-text('Approve diagram')"],
 ["wait", ".approval button:not([disabled])"],
 ["screenshot", "portal/tests/evidence/review-fixture.png"],
 ["click", ".approval button"],
 ["wait", "select[name=device_id]"],
 ["click", "nav a[href='#devices']"],
 ["wait", "form.pair"],
 ["fill", "input[name=pair_code]", "4F7K"],
 ["fill", "input[name=worker_name]", "Bay 3"],
 ["click", "form.pair button"],
 ["wait", "td:has-text('Bay 3')"],
 ["click", "nav a[href='#assign']"],
 ["wait", "select[name=device_id]"],
 ["select", "select[name=device_id]", "LNS-1"],
 ["select", "select[name=procedure]", "SOP-150/A"],
 ["click", "button:has-text('Assign task')"],
 ["wait", ".board-table td:has-text('1/6')"],
 ["js", "window.fixtureStarted = performance.now(); fetch('/__fixture/next', {method:'POST'}).then(r => r.json())"],
 ["wait", ".board-table td:has-text('2/6')"],
 ["js", "JSON.stringify({fixtureBoardUpdateMs: Math.round(performance.now()-window.fixtureStarted), hasDeviation: document.body.textContent.includes('Synthetic witness mark missing.'), syntheticBanner: document.body.textContent.includes('Demo build: upload synthetic material only.')})"],
 ["screenshot", "portal/tests/evidence/board-fixture.png"],
 ["viewport", "375x812"],
 ["screenshot", "portal/tests/evidence/board-mobile-fixture.png"],
 ["console", "--errors"]
]
'@
$steps = $steps.Replace('__FILE__', (Resolve-Path 'portal/tests/synthetic-sop.txt').Path.Replace('\', '/'))
$trace = $steps | & $Browse chain 2>&1 | Out-String
$trace | Set-Content -LiteralPath portal/tests/evidence/browser-fixture.txt
Write-Output $trace
if ($LASTEXITCODE -ne 0 -or $trace -match 'ERROR:|timed out' -or $trace -notmatch 'fixtureBoardUpdateMs') { throw 'Fixture browser smoke failed; inspect browser-fixture.txt' }
