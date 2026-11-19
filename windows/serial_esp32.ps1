param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^COM[1-9][0-9]*$')]
    [string]$Puerto,
    [ValidateSet('ASTRA1', 'ASTRA2')]
    [string]$Protocolo = 'ASTRA1'
)

$ErrorActionPreference = 'Stop'
$serie = [System.IO.Ports.SerialPort]::new($Puerto, 115200)
$serie.NewLine = "`n"
$serie.WriteTimeout = 750
$serie.ReadTimeout = 250

function Esperar-Respuesta([string]$Esperada, [int]$Milisegundos) {
    $reloj = [System.Diagnostics.Stopwatch]::StartNew()
    while ($reloj.ElapsedMilliseconds -lt $Milisegundos) {
        try {
            $respuesta = $serie.ReadLine().Trim()
        } catch [System.TimeoutException] {
            continue
        }
        if ($respuesta -ceq $Esperada) { return }
        if ($respuesta -cmatch '^(ERR|BUSY)( |$)') {
            throw "ESP32 devolvió '$respuesta' al esperar '$Esperada'."
        }
    }
    throw [System.TimeoutException]::new("ESP32 no devolvió '$Esperada' antes del tiempo límite.")
}

try {
    $serie.Open()
    $serie.DiscardInBuffer()
    # HELLO confirma el protocolo sin ordenar ningún movimiento.
    for ($intento = 1; $intento -le 4; $intento++) {
        $serie.WriteLine("HELLO $Protocolo")
        try {
            Esperar-Respuesta "READY $Protocolo" 750
            break
        } catch [System.TimeoutException] {
            if ($intento -eq 4) { throw }
        }
    }
    [Console]::WriteLine("READY $Protocolo")
    while ($null -ne ($linea = [Console]::ReadLine())) {
        if ($linea -cnotmatch '^([PF]) ([1-9][0-9]*) [-+0-9.eE]+ [-+0-9.eE]+ [-+0-9.eE]+$') {
            throw 'Solicitud serial inválida.'
        }
        $tipo = $Matches[1]
        $id = $Matches[2]
        if ($tipo -eq 'F' -and $Protocolo -ne 'ASTRA2') { throw 'El modo rostro requiere ASTRA2.' }
        $serie.WriteLine($linea)
        Esperar-Respuesta "ACK $id" 750
        $limite = if ($tipo -eq 'F') { 4800 } else { 2500 }
        Esperar-Respuesta "DONE $id" $limite
        [Console]::WriteLine("DONE $id")
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    $serie.Dispose()
}
