const run = (c) => mc.call('command.run', { command: c });
run('gamerule doDaylightCycle false');
run('weather clear 1000000');
run('gamemode creative Dev');
run('fill 108 -63 -208 132 -54 -192 air');
run('fill 108 -63 -208 132 -63 -192 stone');
mc.call('screen.close', {});
