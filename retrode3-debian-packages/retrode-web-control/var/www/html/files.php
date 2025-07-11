<?php

include("header.inc.php");

html("<h2>Files</h2>");

# echo "<p>";
$link="smb://".$_SERVER['SERVER_ADDR']."/retrode";
echo "<a href=\"$link\">Open through SMB</a> ";
echo "</p>";

$root="/usr/local/games/retrode";	// path on retrode device
if(!file_exists($root))
	$root ="/Volumes/Retrode3/retrode-setup/usr/local/games/retrode";	// on development host

$d=getvar("dir");
$dir=str_replace("/..", "", "/$d");	// prevent moving to superdirectories..
$dir=ltrim($dir, "./");			// strip off first / or .

// text("root: $root d: $d dir: $dir");

function scansubdirs($dir)
{
	$root = scandir($dir);
	foreach($root as $value)
	{
		if($value === '.' || $value === '..') continue;
		if(!is_dir("$dir/$value"))
			{
			$result[]="$dir/$value";
			continue;
			}
		foreach(scansubdirs("$dir/$value") as $value)
			$result[]=$value;
	}
	return $result;
}

echo "<table border=\"1\">";
foreach(scandir("$root/$dir") as $item)
{
	if($item === '.') continue;
	// skip files starting with .?
	if(!$dir && $item === '..') continue;	// not for root
	echo "<tr>";
	if(is_dir("$root/$dir/$item"))
		{ // directory
		if($item === '..')
			{
			$size="Parent";
			$file="$here?dir=".ltrim(dirname($dir), "./");	// strip off first / or .
			}
		else
			{
			$size="Directory";
			$file="$here?dir=".ltrim("$dir/$item", "./");	// strip off first / or .
			}
		}
	else
		{ // regular file
		$size=filesize("$root/$dir/$item");
		$file="$here?download=".ltrim("$dir/$item", "./");	// strip off first / or .
		}
	echo "<td>".$size."</td>";
	echo "<td><a href=\"".$file."\">".htmlentities($item)."</a></td></tr>";
	echo "</tr>";
}
echo "<table>";

include("footer.inc.php");
?>
