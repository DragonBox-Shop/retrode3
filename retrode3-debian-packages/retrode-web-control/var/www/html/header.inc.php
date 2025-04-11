<?php
// echo "this is the header";
// create header

if(true)
{
	ini_set('display_errors', 1);
	ini_set('display_startup_errors', 1);
	error_reporting(E_ALL);
}

// download manager

// print_r($_SERVER);
$here=strtok($_SERVER["REQUEST_URI"], '?');	// without query part
// echo $here;

if(isset($_GET['download']))
	{ // handle file download
	$path=$_GET['download'];
	$path="/usr/local/games/retrode/".$path;
	// check if permitted... i.e. strip off any .. or initial /
	if(!file_exists($path))
		{
		header($_SERVER["SERVER_PROTOCOL"]." 404 Not Found");
		header("Status: 404 Not Found");
		$_SERVER['REDIRECT_STATUS'] = 404;
		// echo "<DOCTYPE>";
		echo "<html>";
		echo "<head>";
		echo "<title>404 Not Found</title>";
		echo "<meta name=\"generator\" content=\"retrode\">";	// a hint that the script is running
		echo "</head>";
		echo "<body>";
		echo "<h1>Not Found</h1>";
		echo "<p>The requested URL ";
		echo htmlentities($_SERVER['PHP_SELF']);
		if($_SERVER['QUERY_STRING'])
			echo "?".htmlentities($_SERVER['QUERY_STRING']);
		echo " was not found on this server.</p>";
// print_r($path);
	// FIXME: optionally notify someone?
		echo "</body>";
		echo "</html>";
		exit;
		}
	header("Content-Type: application/octet-stream");
	header("Content-Length: ".filesize($path));
	header("Content-Disposition: attachment; filename=".basename($path));
//	header("Refresh: 0; url=$here");	// it is not clear if this is standard or non-standard: https://stackoverflow.com/questions/283752/refresh-http-header
	readfile($path);	// send file
	exit;
	}
if(isset($_GET['delete']))
	{ // handle file delete
	$path=$_GET['delete'];
	// check if permitted...
	// if yes, delete file
		echo "delete $path";
		exit;
	}
?>

<form method="POST" action="<?php echo $here;?>">
<img src="https://dragonbox.de/img/dragonbox-logo-15724157971.jpg"/>
<h1>Welcome to retrode 3</h1>
<?php
echo $_SERVER['REMOTE_ADDR']." ";
echo date(DATE_RFC822)." ";
?>
<input type="submit" value="Refresh"></input>
<h2>
<a href="index.php">Main</a>
<a href="files.php">Files</a>
<a href="mapper.php">Mapper</a>
<a href="settings.php">Settings</a>
</h2>

