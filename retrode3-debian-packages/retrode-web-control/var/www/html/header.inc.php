<?php
// echo "this is the header";
// create header

if(true)
{
	ini_set('display_errors', 1);
	ini_set('display_startup_errors', 1);
	error_reporting(E_ALL);
}

/* general helper functions */

function getvar($name)
{
	if(isset($_GET[$name]))
		return $_GET[$name];
	if(isset($_POST[$name]))
		return $_POST[$name];
	return "";
}

// SECURITY NOTE: this should be the only locations where direct "echo" is used!

function html($html)
	{
	echo $html;
	}

function _htmlentities($value)
	{
	return htmlentities($value, ENT_COMPAT | ENT_SUBSTITUTE, 'UTF-8');
	}

function parameter($name, $value)
	{
	// FIXME: use htmlentites($value) like for _value - or only optional???
	// also for name?
	html(" $name=\"".$value."\"");
	}

function text($text)
	{
	html(_htmlentities($text));
	}

function callcmd($command)
{ // call command with sudo environment

// FIXME: poweroff: must run as superuser.
// see: https://stackoverflow.com/questions/67292960/how-to-run-a-shell-as-root-from-php-apache

	system($command);
	return;

	$p=popen($command, "r");
	$result=stream_get_contents($p);
	$exit=pclose($p);
	text($result);
}

/* download manager */

// print_r($_SERVER);
$here=strtok($_SERVER["REQUEST_URI"], '?');	// without query part
// echo $here;

if($dlpath=getvar('download'))
	{ // handle file download
	$dlpath="/usr/local/games/retrode/".$dlpath;
	$dlpath=str_replace("/..", "", $dlpath);
	if(!file_exists($dlpath))
		{
		header($_SERVER["SERVER_PROTOCOL"]." 404 Not Found");
		header("Status: 404 Not Found");
		$_SERVER['REDIRECT_STATUS'] = 404;
		// echo "<DOCTYPE>";
		html("<html>");
		html("<head>");
		html("<title>"); text("404 Not Found"); html("</title>");
		echo "<meta name=\"generator\" content=\"retrode\">";	// a hint that the script is running
		html("</head>");
		html("<body>");
		echo "<h1>Not Found</h1>";
		echo "<p>The requested URL ";
		echo htmlentities($_SERVER['PHP_SELF']);
		if($_SERVER['QUERY_STRING'])
			echo "?".htmlentities($_SERVER['QUERY_STRING']);
		echo " was not found on this server.</p>";
// print_r($dlpath);
	// FIXME: optionally notify someone?
		html("<//body>");
		html("</html>");
		exit;
		}
	header("Content-Type: application/octet-stream");
	header("Content-Length: ".filesize($dlpath));
	header("Content-Disposition: attachment; filename=".basename($dlpath));
//	header("Refresh: 0; url=$here");	// it is not clear if this is standard or non-standard: https://stackoverflow.com/questions/283752/refresh-http-header
	readfile($dlpath);	// send file
	exit;
	}

if($dlpath=getvar('delete'))
	{ // handle file delete
	// check if permitted...
	// if yes, delete file
		text("delete $dlpath - not implemented");
		exit;
	}
?>
<html>
<head>

</head>
<body>
<form method="POST" action="<?php echo $here;?>">
<a href="https://www.retrode.com"><img style="height: 80px;" src="https://www.retrode.com/wp-content/uploads/2025/03/Retrode-Logo-768x162.webp"/></a>

<?php
$model=str_replace(chr(0), '', file_get_contents("/proc/device-tree/model"));
echo "<h1>Welcome to $model</h1>";
echo $_SERVER['REMOTE_ADDR']." ";
echo date(DATE_RFC822)." ";
?>
<input type="submit" value="Refresh"></input>
<h2>
<a href="index.php">Main</a>
<a href="files.php">Files</a>
<a href="mapper.php">Mapper</a>
<a href="settings.php">Settings</a>
<a href="feedback.php">Feedback</a>
<a href="https://www.retrode.com">Info</a>
</h2>

