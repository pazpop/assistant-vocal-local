<#
Installe Jarvis de zero sur Windows : Python et Ollama (confirmation
demandee individuellement pour chacun, via winget), puis le projet
lui-meme (venv, dependances Python, modele Ollama, voix Piper).

Ne necessite pas Git au prealable : le depot est recupere en .zip si ce
script n'est pas deja lance depuis une copie locale (clonee ou telechargee).

Usage, sans rien avoir installe au prealable (ouvre PowerShell) :
  irm https://raw.githubusercontent.com/pazpop/assistant-vocal-local/main/install.ps1 | iex

Usage, depuis une copie deja presente (clonee ou dezippee) :
  .\install.ps1

Ce script installe le PROJET, pas la fonctionnalite domotique/meteo/etc
(voir config.yml apres coup) et ne lance PAS Jarvis a la fin : la derniere
etape affiche la commande a taper toi-meme.
#>

$ErrorActionPreference = "Stop"

$RepoZipUrl = "https://github.com/pazpop/assistant-vocal-local/archive/refs/heads/main.zip"
$RepoFolderName = "assistant-vocal-local"
$ModeleOllama = "qwen2.5:7b"

function Confirmer([string]$Message) {
    $reponse = Read-Host "$Message [O/n]"
    return -not ($reponse -match '^(n|non|no)$')
}

function Quitter([int]$Code) {
    # Lance via clic droit > "Executer avec PowerShell" (ou double-clic sur
    # install.bat), la fenetre se ferme SEULE des que le script se termine
    # — succes ou erreur — sans ce pause, impossible de lire le dernier
    # message (la commande pour lancer Jarvis, ou l'erreur qui explique
    # pourquoi l'installation s'est arretee).
    Write-Host ""
    Read-Host "Appuie sur Entree pour fermer cette fenetre" | Out-Null
    exit $Code
}

function Update-Path {
    # Les paquets installes via winget dans cette meme session ne sont pas
    # forcement visibles tant que le PATH n'est pas relu depuis le registre
    # (piege classique : "commande introuvable" juste apres une install qui
    # a pourtant reussi).
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Test-TcpPort([string]$ComputerName, [int]$Port, [int]$TimeoutMs = 2000) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($ComputerName, $Port, $null, $null)
        $succes = $async.AsyncWaitHandle.WaitOne($TimeoutMs) -and $client.Connected
        return [bool]$succes
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-WingetPackageInstalled([string]$WingetId) {
    winget list --id $WingetId -e --accept-source-agreements *> $null
    return $LASTEXITCODE -eq 0
}

function Install-Paquet([string]$NomAffiche, [string]$WingetId) {
    if (Test-WingetPackageInstalled $WingetId) {
        Write-Host "OK - $NomAffiche est deja installe."
        return
    }
    Write-Host ""
    Write-Host "$NomAffiche n'est pas installe."
    if (-not (Confirmer "L'installer maintenant via winget ($WingetId) ?")) {
        throw "$NomAffiche est requis pour continuer. Installation annulee."
    }
    winget install --id $WingetId -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Echec de l'installation de $NomAffiche (code winget $LASTEXITCODE)."
    }
    Update-Path
    Write-Host "OK - $NomAffiche installe."
}

function Show-GPU {
    $controleurs = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Name
    $nvidia = $controleurs | Where-Object { $_ -match 'NVIDIA' }
    $amd = $controleurs | Where-Object { $_ -match 'AMD|Radeon' }

    if ($nvidia) {
        Write-Host "Carte NVIDIA detectee ($($nvidia -join ', ')) - projet completement compatible (transcription accelérée par GPU)." -ForegroundColor Green
    } elseif ($amd) {
        Write-Host "Carte AMD detectee ($($amd -join ', ')) - faster-whisper (transcription) ne supporte que CUDA/NVIDIA : le projet va rouler en CPU, donc quelques latences a prevoir. Voir 'GPU AMD' dans ARCHITECTURE.md pour ajuster config.yml en consequence (stt.device: cpu)." -ForegroundColor Yellow
    } else {
        $liste = if ($controleurs) { $controleurs -join ', ' } else { 'aucune carte detectee' }
        Write-Host "Pas de carte NVIDIA/AMD dediee detectee ($liste) - le projet va rouler en CPU, donc quelques latences a prevoir. Voir 'GPU AMD' dans ARCHITECTURE.md pour ajuster config.yml en consequence (stt.device: cpu)." -ForegroundColor Yellow
    }
}

# Tout le corps du script est dans ce try/catch : n'importe quelle erreur
# (la mienne via throw, ou une exception inattendue - reseau coupe, disque
# plein...) doit afficher un message clair ET marquer une pause avant de
# fermer la fenetre, jamais juste planter avec une trace technique illisible
# qui disparait aussitot (voir Quitter ci-dessus pour le pourquoi de la pause).
try {
    Write-Host "=== Jarvis - installation ===" -ForegroundColor Cyan
    Write-Host ""
    Show-GPU
    Write-Host ""

    # --- 0. winget disponible ? ---
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget est introuvable. Mets a jour Windows ou installe 'App Installer' depuis le Microsoft Store, puis relance ce script."
    }

    # --- 1. Python et Ollama (confirmation individuelle, aucune install a l'insu) ---
    Install-Paquet "Python 3.11" "Python.Python.3.11"
    Install-Paquet "Ollama" "Ollama.Ollama"
    # Pas requis par Jarvis lui-meme (faster-whisper/Piper n'en ont pas
    # besoin) : uniquement pour les fonctions audio propres a Open WebUI
    # (bouton micro, upload de fichiers audio dans son interface), via la
    # dependance pydub. Propose quand meme (pas conditionne a la presence
    # d'Open WebUI, installe separement) : installer ffmpeg ne fait jamais
    # de mal et evite d'avoir a relancer ce script plus tard pour ca.
    Install-Paquet "ffmpeg (fonctions audio d'Open WebUI)" "Gyan.FFmpeg"

    # --- 2. Emplacement du projet : deja present, ou a telecharger (.zip, pas besoin de git) ---
    if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "requirements.txt"))) {
        $ProjetDir = $PSScriptRoot
        Write-Host "OK - Projet deja present : $ProjetDir"
    } else {
        Write-Host ""
        if (-not (Confirmer "Telecharger le depot assistant-vocal-local dans $(Get-Location)\$RepoFolderName ?")) {
            throw "Le depot du projet est requis pour continuer. Installation annulee."
        }
        $ProjetDir = Join-Path (Get-Location) $RepoFolderName
        if (Test-Path $ProjetDir) {
            throw "$ProjetDir existe deja. Supprime-le, ou relance ce script depuis l'interieur si c'est deja le depot."
        }
        $ZipPath = Join-Path $env:TEMP "assistant-vocal-local.zip"
        $ExtractDir = Join-Path $env:TEMP "assistant-vocal-local-extract"
        Write-Host "Telechargement du depot..."
        Invoke-WebRequest -Uri $RepoZipUrl -OutFile $ZipPath
        if (Test-Path $ExtractDir) { Remove-Item $ExtractDir -Recurse -Force }
        Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force
        Remove-Item $ZipPath
        $DossierExtrait = Get-ChildItem -Path $ExtractDir -Directory | Select-Object -First 1
        Move-Item $DossierExtrait.FullName $ProjetDir
        Remove-Item $ExtractDir -Recurse -Force
        # Pas de Git ici : on note le commit telecharge, pour que launch.py
        # puisse dire si le code est a jour (sans reseau, on saute : optionnel).
        try {
            $Sha = (Invoke-RestMethod -Uri "https://api.github.com/repos/pazpop/assistant-vocal-local/commits/main" -Headers @{ Accept = "application/vnd.github.sha" } -TimeoutSec 10).ToString().Trim()
            Set-Content -Path (Join-Path $ProjetDir ".version") -Value $Sha -Encoding ascii
        } catch {
            Write-Host "Version du depot non enregistree (GitHub injoignable) : la verification de mise a jour sera ignoree."
        }
        Write-Host "OK - Depot pret : $ProjetDir"
    }

    Set-Location $ProjetDir

    # --- 3. Le projet lui-meme (venv, dependances, modele LLM, voix) ---
    Write-Host ""
    if (-not (Confirmer "Installer les dependances du projet (venv Python, pip, modele Ollama $ModeleOllama [~4,7 Go], voix Piper) ?")) {
        throw "Installation annulee."
    }

    if (-not (Test-Path ".venv")) {
        Write-Host "Creation du venv (Python 3.11)..."
        py -3.11 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Creation du venv impossible (Python 3.11 installe ? ouvre un nouveau terminal apres l'installation de Python)." }
    }

    Write-Host "Installation des dependances Python (peut prendre plusieurs minutes)..."
    & .\.venv\Scripts\pip.exe install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "L'installation des dependances Python a echoue (voir l'erreur pip ci-dessus)." }
    Write-Host "Rappel : sur GPU AMD ou sans GPU, voir 'GPU AMD' dans ARCHITECTURE.md (les paquets nvidia-cublas-cu12/nvidia-cudnn-cu12 installes ci-dessus sont alors inutiles, sans consequence sur le fonctionnement)."

    if (-not (Test-Path "config.yml")) {
        Copy-Item "config.yml.example" "config.yml"
        Write-Host "OK - config.yml cree depuis le modele."
    }

    Write-Host ""
    Write-Host "Verification qu'Ollama repond (peut prendre un instant au premier demarrage)..."
    $OllamaPret = $false
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-TcpPort "localhost" 11434) {
            $OllamaPret = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $OllamaPret) {
        throw "Ollama ne repond toujours pas sur http://localhost:11434. Lance l'application Ollama manuellement (menu Demarrer), puis relance ce script : les etapes deja faites seront sautees."
    }

    Write-Host "Telechargement du modele $ModeleOllama (~4,7 Go si pas deja present, peut prendre du temps)..."
    ollama pull $ModeleOllama
    if ($LASTEXITCODE -ne 0) { throw "Le telechargement du modele $ModeleOllama a echoue (reseau ? espace disque ?)." }

    if (-not (Test-Path "models\piper\fr_FR-tom-medium.onnx")) {
        Write-Host "Telechargement de la voix Piper..."
        Push-Location "models\piper"
        try {
            & "..\..\.venv\Scripts\python.exe" -m piper.download_voices fr_FR-tom-medium
            if ($LASTEXITCODE -ne 0) { throw "Le telechargement de la voix Piper a echoue." }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "OK - Voix Piper deja presente."
    }

    Write-Host ""
    Write-Host "=== Installation terminee ===" -ForegroundColor Green
    Write-Host "Pense a adapter ta ville dans config.yml (section location:) si ce n'est pas deja fait."
    Write-Host ""
    Write-Host "Pour lancer Jarvis :"
    Write-Host "  cd `"$ProjetDir`""
    Write-Host "  .\.venv\Scripts\python.exe launch.py"

    Quitter 0
} catch {
    Write-Host ""
    Write-Host "ERREUR : $($_.Exception.Message)" -ForegroundColor Red
    Quitter 1
}
