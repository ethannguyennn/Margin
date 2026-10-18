# Speaks each line of utterances.txt into wav/<n>.wav as 16 kHz mono 16-bit PCM.
param([string]$Dir = $PSScriptRoot)
Add-Type -AssemblyName System.Speech
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
New-Item -ItemType Directory -Force "$Dir\wav" | Out-Null
$i = 0
foreach ($line in Get-Content "$Dir\utterances.txt") {
    if (-not $line.Trim()) { continue }
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.Rate = 1
    $s.SetOutputToWaveFile("$Dir\wav\$i.wav", $fmt)
    $s.Speak($line)
    $s.Dispose()
    $i++
}
"wrote $i files"
