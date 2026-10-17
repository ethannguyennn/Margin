# Simulator PNGs contain a constant green RGB plane and glyph intensity in
# alpha. Composite QA copies on black so image viewers can display the text.
# Original captures are retained unchanged beside the previews.
Add-Type -AssemblyName System.Drawing
$lensArtifactDirectory = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../test-artifacts'))
Get-ChildItem -LiteralPath $lensArtifactDirectory -Filter '*-glasses.png' | ForEach-Object {
    $lensSource = [System.Drawing.Bitmap]::new($_.FullName)
    $lensPreview = [System.Drawing.Bitmap]::new($lensSource.Width, $lensSource.Height)
    $lensGraphics = [System.Drawing.Graphics]::FromImage($lensPreview)
    try {
        $lensGraphics.Clear([System.Drawing.Color]::Black)
        $lensGraphics.DrawImage($lensSource, 0, 0, $lensSource.Width, $lensSource.Height)
        $lensPreview.Save((Join-Path $lensArtifactDirectory ($_.BaseName + '-preview.png')))
    } finally {
        $lensGraphics.Dispose()
        $lensPreview.Dispose()
        $lensSource.Dispose()
    }
}
