$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$securePassword = Read-Host 'Mot de passe PostgreSQL local (saisie masquee)' -AsSecureString
$secretPointer = [IntPtr]::Zero
try {
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
    $encodedPassword = [System.Uri]::EscapeDataString($plainPassword)
    $env:TOURISMO_DB_PASSWORD = $plainPassword
    $env:TOURISMO_DATABASE_URL = ('postgresql://tourismo:{0}@127.0.0.1:5432/tourismo' -f $encodedPassword)
    $plainPassword = $null
    $encodedPassword = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    $secretPointer = [IntPtr]::Zero
    & (Join-Path $repo '.venv\Scripts\python.exe') -m scripts.lot4_clip_recipe
    if ($LASTEXITCODE -ne 0) {
        throw ('Recette CLIP interrompue. Code Python : {0}' -f $LASTEXITCODE)
    }
    Write-Host 'Recette CLIP terminee. Voir data/lot-4/b-clip-recipe.json et b-clip-warm.json.'
}
finally {
    if ($secretPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    }
    Remove-Item Env:TOURISMO_DB_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:TOURISMO_DATABASE_URL -ErrorAction SilentlyContinue
    $plainPassword = $null
    $encodedPassword = $null
    $securePassword = $null
}
