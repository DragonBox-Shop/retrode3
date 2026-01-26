<?php

include("header.inc.php");

// html("<h2>Files</h2>");

# echo "<p>";
$link="smb://".$_SERVER['SERVER_ADDR']."/retrode";
echo "<a href=\"$link\">Open through SMB</a> ";
echo "</p>";

$root="/usr/local/games";	// "chroot" on retrode device
if(!file_exists($root))
	$root ="/Volumes/Retrode3/Retrode3-Software/retrode3-debian-packages/retrode-tools/$root";	// a copy on development host

$d=getvar("file");
$file=str_replace("/..", "", "/$d");	// prevent moving to superdirectories..
$file=ltrim($file, "./");			// strip off first / or .

html("<h2>"); text("Current directory: /$file"); html("</h2>");

$mode=getvar("mode");
if($mode == "analyse")
{
	html("<pre>");
	text(callcmd("cd /tmp; /usr/local/bin/ucon64 '$root/$file'"));
	$file=dirname($file);	// strip off file name
	html("</pre>");
}
// text("root: $root d: $d file: $file");
if(file_exists("$root/$file"))
{
	echo "<table border=\"1\">";
	echo "<r><th>Name</th><th>Last modified</th><th>Size</th><tr>";
	foreach(scandir("$root/$file") as $item)
		{
	if($item === '.') continue;
	// skip other hidden files starting with .?
	if(!$file && $item === '..') continue;	// not for root
	html("<tr>");
	$modified=date ("F d Y H:i:s", filemtime("$root/$file/$item"));
	if(is_dir("$root/$file/$item"))
		{ // directory
		if($item === '..')
			{
			$name="Parent";
			$size="-";
			$link="$here?file=".urlencode(ltrim(dirname($file), "./"));	// strip off first / or .
			}
		else
			{
			$name="$item/";
			$size="-";
			$link="$here?file=".urlencode(ltrim("$file/$item", "./"));	// strip off first / or .
			}
		}
	else
		{ // regular file
		$name=$item;
		$size=filesize("$root/$file/$item");
		if($size > 1024*1024)
			$size=str_replace(".0M", "M", sprintf("%.1fM", $size/1024.0*1024));
		if($size > 1024)
			$size=str_replace(".0K", "K", sprintf("%.1fK", $size/1024.0));
		$link="$here?download=".urlencode(ltrim("$file/$item", "./")); // strip off first / or .
		}
	html("<td width=\"200px\">");
	html("<a href=\"".$link."\">"); text($name); html("</a>");
	html("</td>");
	html("<td align=\"right\">"); text($modified); html("</td>");
	html("<td align=\"right\">");
	text($size);
	if($size != "-")
		{ // include file name in file=
		$link="$here?file=".ltrim("$file/$item", "./"); // strip off first / or .
		html("<a href=\"".$link."&mode=analyse"."\"> ");
		text("Analyse");
		html("</a>");
		}
	html("</td>");
	html("</tr>");
		}
	echo "<table>";
}
else
{
	text("Not found: $file ");
	$name="Parent directory";
	$link="$here?file=".urlencode(ltrim(dirname($file), "./"));	// strip off first / or .
	html("<a href=\"".$link."\">"); text($name); html("</a>");
}

include("footer.inc.php");
?>
