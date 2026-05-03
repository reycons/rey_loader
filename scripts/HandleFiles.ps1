$WinSCPPath = "D:\Program Files (x86)\WinSCP\WinSCPnet.dll"
$ConfigPath = "D:\Navi\Bin\HandleFiles.config"
[XML]$Config = Get-Content $ConfigPath
 
function GetDate($Node){

	Switch ([int](Get-Date).DayOfWeek){
		0 {$LoadDate = (Get-Date).AddDays(-2 + $Node.Lookback)}
		1 {$LoadDate = (Get-Date).AddDays(-3 + $Node.Lookback)}
		default {
			$LoadDate = (Get-Date).AddDays(0 + $Node.Lookback)
			}
		}
	return $LoadDate.ToString($Node.DateFormat)
}

function RunFTPSessions (){
	$Config.SelectNodes('//Configuration/FTP/Server') | ForEach-Object {
		$DateString = GetDate($_)
		$_.RemoteFiles = $_.RemoteFiles.Replace('[DateString]', $DateString)
write-host "Getting Files:" $_.UserName $_.RemoteFiles
		FTPFiles($_)
        IndexFiles($_)
		}
	
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

	$session = New-Object WinSCP.Session

	try{
		$session.Open($sessionOptions)
		$TransferOptions = New-Object WinSCP.TransferOptions
		$TransferOptions.TransferMode = [WinSCP.TransferMode]::Binary
		$TransferResult = $session.GetFiles($ServerInfo.RemoteFiles, $ServerInfo.LocalFolder, $False, $TransferOptions)
		}
	finally{
		$session.Dispose()
	}
}

function IndexFiles($ServerInfo){
	$Config.SelectNodes('//Configuration/FTP/Server') | ForEach-Object {
		$DateString = GetDate($_)
		$_.RemoteFiles = $_.RemoteFiles.Replace('[DateString]', $DateString)
		FTPFiles($_)
        IndexFiles($_)
		}
	
    
}

function main(){
    Clear-Host
   RunFTPSessions

}

main

