    #read-host "Enter Password or UserName" -AsSecureString | convertFrom-SecureString

    
    
    $SecurePassword = "01000000d08c9ddf0115d1118c7a00c04fc297eb01000000cbdc1bf68a61124a89d11c2d9196f0a600000000020000000000106600000001000020000000e319cffa77f08a2901d18bae17d83dc45b6ffee7cbd5887fb2e05f50e8c16b79000000000e8000000002000020000000217033ada924123b9dffe14e881967a848c396bd6961b7405bff9335ed3f431210000000a9900d1619dd39495107138371cf6a9d40000000411901ae279236ee3200b13b915a4c140dbccd0f2ca2d81856aca1ab831a9b4c2b84c98a1baf40527dd9c5ff7e2bab379b45f672de1998f547b0c209346ad4fd"
    echo $SecurePassword
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
    $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    echo $Password

