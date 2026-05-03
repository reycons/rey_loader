$WinSCPPath = "D:\Program Files (x86)\WinSCP\WinSCPnet.dll"
$ConfigPath = "D:\Navi\Bin\Sys.config"
[XML]$Config = Get-Content $ConfigPath
import-module "sqlps" -DisableNameChecking

function GetDate($Node){
	Switch ([int](Get-Date).DayOfWeek){
		0 {$LoadDate = (Get-Date).AddDays(-1 + $Node.Lookback)}
		1 {$LoadDate = (Get-Date).AddDays(-2 + $Node.Lookback)}
		default {
			$LoadDate = (Get-Date).AddDays(0 + $Node.Lookback)
			}
		}
    return $LoadDate
#return [datetime]"1/10/2020"
    
} 

function GetFormattedDate($Node){
    $LoadDate = GetDate($Node)
	return $LoadDate.ToString($Node.DateFormat)
}

function RunFTPSessions (){
    $PSFTPath = $Config.Configuration.FTP.PSFTPPath
	$Config.SelectNodes('//Configuration/FTP/Server') | ForEach-Object {
		$DateString = GetFormattedDate($_)
write-host "Getting Files:" $_.UserName $_.Description

# WinSCP is very slow use PSFTP instead
#		FTPFiles($_) 

        PSFTP($_)
		}
	
}

function PSFTP($ServerInfo){
    $CommandFile =  $ServerInfo.FTPCommandFile

	$DateString = GetFormattedDate($ServerInfo)
    $SecurePassword = ConvertTo-SecureString $ServerInfo.Password
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
    $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
#write-host "password:" $Password

    $FtpCommand = $Config.Configuration.FTP.PSFTPPath 
    $Args = $ServerInfo.HostName + " -batch -l " + $ServerInfo.UserName + " -pw " + $password + " -b " + $CommandFile
#write-host "Args:" $Args
    $Line = $ServerInfo.Commands
    if ($Line -like '*[DateString]*'){$Line = $Line.Replace('[DateString]', $DateString)}
    Set-Content -Path $CommandFile -Value $Line
    $outFile = $CommandFile + ".out"
#write-host "result:" $Result
    Start-Process -Wait -FilePath $FtpCommand -ArgumentList $Args -RedirectStandardOutput $outFile -NoNewWindow


}


function FTPFiles ($ServerInfo){

	# Load WinSCP .NET assembly
	Add-Type -Path $WinSCPPath

	# Set up session options
	$sessionOptions = New-Object WinSCP.SessionOptions -Property @{
		Protocol = $ServerInfo.Protocol
		HostName = $ServerInfo.HostName
		UserName = $ServerInfo.UserName
		SecurePassword = ConvertTo-SecureString $ServerInfo.Password
		SshHostKeyFingerprint = $ServerInfo.SshHostKeyFingerprint

		}
    $sessionOptions.AddRawSettings("SendBuf", "0")
	$session = New-Object WinSCP.Session

	try{
		$session.Open($sessionOptions)
		$TransferOptions = New-Object WinSCP.TransferOptions
#		$TransferOptions.TransferMode = [WinSCP.TransferMode]::Binary
		$TransferResult = $session.GetFiles($ServerInfo.RemoteFiles, $ServerInfo.LocalFolder, $False, $TransferOptions)
		}
	finally{
		$session.Dispose()
	}
}

function IndexAllFiles(){
    $IndexPath = $Config.Configuration.IndexLocations.IndexFileName
    $IndexHeader = $Config.Configuration.IndexHeader.HeaderRow
	$Config.SelectNodes('//Configuration/IndexLocations/IndexLocation') | ForEach-Object {
		$DateString = GetFormattedDate($_)
        $FileDate = GetDate($_)
        $IndexFile = $IndexPath.Replace('[DateString]', $DateString)
        $IndexFile = $IndexFile.Replace('[Name]', $_.Name)
        Set-Content -Path $IndexFile -Value $IndexHeader
		$_.Folder = $_.Folder.Replace('[DateString]', $DateString)
        $files = Get-ChildItem -Path $_.Folder
        write-host "Indexing:" $_.Folder 
        foreach ($file in $files){
            Write-host "Reading File:" $file.FullName
            $RowCount = Get-Content $file.FullName | Measure-Object -Line
            $Header = Get-Content $file.FullName -First 1
            $FileCharacteristics = $IndexFile
            $FileCharacteristics += "|"
            $FileCharacteristics += $FileDate.toString('yyyy-MM-dd')
            $FileCharacteristics += "|"
            $FileCharacteristics += Get-Date -Format G
            $FileCharacteristics += "|"
            $FileCharacteristics += $file.FullName
            $FileCharacteristics += "|"
            $FileCharacteristics += $file.Length
            $FileCharacteristics += "|"
            $FileCharacteristics += $file.LastWriteTime
            $FileCharacteristics += "|"
            $FileCharacteristics += $RowCount.Lines
            $FileCharacteristics += "|"
            $FileCharacteristics += $Header
#Write-host "Reading File:" $FileCharacteristics
            Add-Content -Path $IndexFile -Value $FileCharacteristics

        }
	}    
}



 function SyncAllFolders(){
# not done !!!!!
	$Config.SelectNodes('//Configuration/Copy/Folder') | ForEach-Object {
		$DateString = GetFormattedDate($_)
		$_.Filter = $_.Filter.Replace('[DateString]', $DateString)
        $_.From = $_.From + $_.filter
write-host "Copying Files:" $_.From "To" $_.To
        CopyFolder($_)
		}
	
}
 
Function CopyFolder($Node){
    
    Copy-Item -Path $Node.From -Recurse -Destination $Node.To
}
 
Function SetTime($Node){
    [XML]$Time = Get-Content $ConfigPath
    $Element = $Time.SelectSingleNode($Node)
    $Element.InnerText = (Get-Date).ToString()
    $Time.Save($ConfigPath)
    
}

function RunSQL(){
    $Server = $Config.Configuration.SQLServer.Server.Name
Write-Host 'Server:' $Server
    $Database = $Config.Configuration.SQLServer.Server.Database
Write-Host 'Database:' $Database
    foreach ($Command in $Config.Configuration.SQLServer.Server.Commands.Command){
        Write-Host 'Running Query:' $Command.sql
        Invoke-SQLCmd -QueryTimeout 0 -ServerInstance $Server -Database $Database -Query $Command.sql
    }
}

function ExpandFiles(){

    foreach ($File in $Config.Configuration.FileCompression.ExpandFiles.File){
    	$DateString = GetFormattedDate($File)
        $FileName = $file.Name

        if ($FileName -like '*[DateString]*'){$FileName = $FileName.Replace('[DateString]', $DateString)}
write-host "Expanding Files:" $FileName
        Get-ChildItem -Path $Filename | Expand-Archive -DestinationPath $file.Destination -Force
        if($File.KeepZip = "False"){remove-Item $FileName}
    }
}


function main(){
    Clear-Host
    #SetTime("//Configuration/FTP/StartTime")
    RunFTPSessions
    #SetTime("//Configuration/FTP/EndTime")
    SyncAllFolders
    ExpandFiles
    IndexAllFiles
    RunSQL  #This is not running when using windows scheduler
}

main

