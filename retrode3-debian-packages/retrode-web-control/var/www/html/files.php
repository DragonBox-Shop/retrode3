<?php

include("header.inc.php");

// html("<h2>Files</h2>");

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
echo "<r><th>Name</th><th>Last modified</th><th>Size</th><tr>";
foreach(scandir("$root/$dir") as $item)
{
	if($item === '.') continue;
	// skip other hidden files starting with .?
	if(!$dir && $item === '..') continue;	// not for root
	echo "<tr>";
	$modified=date ("F d Y H:i:s", filemtime("$root/$dir/$item"));
	if(is_dir("$root/$dir/$item"))
		{ // directory
		if($item === '..')
			{
			$name="Parent";
			$size="-";
			$file="$here?dir=".ltrim(dirname($dir), "./");	// strip off first / or .
			}
		else
			{
			$name="$item/";
			$size="-";
			$file="$here?dir=".ltrim("$dir/$item", "./");	// strip off first / or .
			}
		}
	else
		{ // regular file
		$name=$item;
		$size=filesize("$root/$dir/$item");
		if($size > 1024*1024)
			$size=str_replace(".0M", "M", sprintf("%.1fM", $size/1024.0*1024));
		if($size > 1024)
			$size=str_replace(".0K", "K", sprintf("%.1fK", $size/1024.0));
		$file="$here?download=".ltrim("$dir/$item", "./");	// strip off first / or .
		}
	echo "<td width=\"200px\"><a href=\"".$file."\">".rawurlencode($name)."</a></td>";
	echo "<td align=\"right\">".$modified."</td>";
	echo "<td align=\"right\">".$size."</td>";
	echo "</tr>";
}
echo "<table>";

include("footer.inc.php");
?>
