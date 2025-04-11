<?php

include("header.inc.php");

?>
</p>
<h2>Files</h2>
<p>
<?php
# echo "<p>";
$link="smb://".$_SERVER['SERVER_ADDR']."/media";
echo "<a href=\"$link\">Open through SMB</a> ";
echo "</p>";

$path="/usr/local/games/retrode";	// on retrode device
if(!file_exists($path))
	$path="/Volumes/Retrode3/retrode-setup/usr/local/games/retrode";	// on development host

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
foreach(scansubdirs($path) as $item)
{
	echo "<tr>";
	$file=substr($item, strlen($path));
	if(is_dir($item))
		{ // directory
		echo "<td></td>";
		echo "<td>".htmlentities($file)."</td>";
		}
	else
		{ // regular file
		  // filesize($path) ausgeben
		echo "<td>".filesize($item)."</td>";
		echo "<td><a href=\"$here?download=".rawurlencode($file)."\">".htmlentities($file)."</a></td></tr>";
		}
	echo "</tr>";
}
echo "<table>";

include("footer.inc.php");
?>
