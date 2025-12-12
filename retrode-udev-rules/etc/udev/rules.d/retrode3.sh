#!/bin/bash -e
#
# this script should be called by udev
# - on card/cart insertion/removal
# - on game controller connect/disconnect
#
# ACTION="change"		# currently we only have change events
# DEVNAME=/dev/slot-md		# the device name of the slot (for slots)
# DEVNAME=""			# for game controller slot
# CHANNEL=0/1/2/3		# for game controllers
# PWD=/				# script runs in root directory
# STATE=			# new device state
#
# check what happens with udevadm monitor --udev --property
#

echo DATE=$(date) SUBSYSTEM=$SUBSYSTEM ACTION=$ACTION DEVNAME=$DEVNAME STATE=$STATE CHANNEL=$CHANNEL @: "$@" >>/tmp/udev-retrode3.log
# set >>/tmp/udev-retrode3.log

case "$ACTION" in
	change )
		if [ "$DEVNAME" ]
		then # real slot with /dev/slot-md etc.

			SLOT=$(basename "$DEVNAME")

			# FIXME: this is 2.9.4 mapping of slots to LEDs only - should read from or a symlink through /sys/class/retrode3/$SLOT/ledname?
			case "$SLOT" in
				slot-md )	LEDNAME=$(echo /sys/class/leds/*:programming-0);;
				slot-snes )	LEDNAME=$(echo /sys/class/leds/*:programming-1);;
				slot-nes )	LEDNAME=$(echo /sys/class/leds/*:programming-2);;
			esac

			SENSENAME=/sys/class/retrode3/$SLOT/sense
			SENSE=$(cat "$SENSENAME" 2>/dev/null)

			case "$SENSE" in	# SENSE="active" / "empty"	# (new) state
				active )
					# make cart visible over USB (configfs)
					# also run C code to handle different addressing magic...
					echo default-on >$LEDNAME/trigger
					;;
				empty )
					# remove cart from USB (configfs)
					echo heartbeat >$LEDNAME/trigger
					;;
			esac
		else # game controller - could also check for DEVPATH == /devices/platform/retrode3/retrode3/gamecontroller

			case "$CHANNEL" in	# CHANNEL=0 .. 3 as by sequence in device tree
# FIXME: we should add something to the retrode3.rule so that the DEV is passed here
				0 ) CH="sega-right"; DEV=/dev/input/event1; LEDNAME=$(echo /sys/class/leds/*:programming-4);;
				1 ) CH="sega-left"; DEV=/dev/input/event2; LEDNAME=$(echo /sys/class/leds/*:programming-3);;
				2 ) CH="snes-right"; DEV=/dev/input/event3; LEDNAME=$(echo /sys/class/leds/*:programming-4);;
				3 ) CH="snes-left"; DEV=/dev/input/event4; LEDNAME=$(echo /sys/class/leds/*:programming-3);;
			esac

			[ -r "$LEDNAME" ] || LEDNAME=$(echo /sys/class/leds/*:heartbeat)	# v2.9.4 has no specific LEDs

			case "$STATE" in	# STATE="connected" / "disconnected"	# (new) state
				connected )
					ln -sf "$DEV" "/dev/input/$CH"
					# make controller visible over USB (configfs)
					# also run C code to handle different addressing magic...
					echo default-on >$LEDNAME/trigger
					;;
				disconnected )
					rm "/dev/input/$CH"
					# remove controller from USB (configfs)
					echo heartbeat >$LEDNAME/trigger
					;;
			esac
		fi
		;;
	add )
		;;
	remove )
		;;
esac

