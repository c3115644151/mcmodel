const run = (c) => mc.call('command.run', { command: c });
// stage 2 starts from the "on" arena: power the network, take one lamp back by hand, then cut power
run('setblock 116 -62 -200 pastoral_home:party_lights[attach=up,facing=south,mode=steady,lit=true]');
run('setblock 114 -61 -200 air');
mc.call('screen.close', {});
