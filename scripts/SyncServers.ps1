$ConfigPath = "D:\Navi\Bin\SyncServers.config"
[XML]$Config = Get-Content $ConfigPath

function SyncAllFolders(){
	$Config.SelectNodes('//Config/Folders/Folder') | ForEach-Object {
        CopyFolder($_)
		}
	
}

function CheckFileStatus($Node){
    Try{

    }
    Catch{
    }
        
}
function SyncFolder($Node){
    $FileWatcher = New-Object System.IO.FileSystemWatcher
    $FileWatcher.Path = $Node.RemoteFolder
    $FileWatcher.IncludeSubdirectories = $True
    $FileWatcher.EnableRaisingEvents
}

Function CopyFolder($Node){
    Write-Host Copying $Node.RemoteFolder to $Node.LocalFolder
    robocopy $Node.RemoteFolder $Node.LocalFolder /s /z
}
clear 
SyncAllFolders