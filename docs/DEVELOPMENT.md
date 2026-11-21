# Build and test

Run the following from the repository root with Python 3.11 or newer. A clean build obtains pinned dependencies and the official dedicated server in the repository's ignored `local/` directory.

```powershell
python build.py --java-home "<JDK 25 directory>" --prepare-runtime
python build.py --java-home "<JDK 25 directory>" --prepare-runtime --fixture control --port 26131 --accept-eula
python build.py --java-home "<JDK 25 directory>" --prepare-runtime --fixture enabled --port 26133 --accept-eula
```

With a prepared server runtime, use `--runtime "<runtime directory>"` in place of `--prepare-runtime`. The runtime directory contains `game.jar`, `lib/` and `runtime.json`. Add `--extra-mod "<other JAR>"` for each additional mod to load in the same fixture. Each test creates a separate generated loopback server under `local/fixtures/`. Install only the production JAR from `build/libs/`. The separate fixture JAR drives tests and writes a receipt alongside its server log.

## Implementation and verification

Mojang's mapped 26.3 dedicated server routes the three-villager panic behavior in `VillagerPanicTrigger.tick` and the five-villager gossip behavior in `Villager.gossip` through `Villager.spawnGolemIfNeeded`. The injection cancels that method at entry. The unrelated `CarvedPumpkinBlock` construction path still runs.

The native fixture gives a synthetic village the recent-sleep memory required for summoning and observes its ordinary panic AI with a visible husk. It also calls the native gossip routine with five eligible villagers. The control fixture loads Fabric and the fixture harness with vanilla spawning behavior and requires both routes to produce iron golems. With the mod installed, the fixture verifies that the same setup has eligible panic opportunities and produces zero village golems. In both cases it places the carved pumpkin through the native server interaction path and checks that the player-created golem and an independently spawned golem both persist.

The tested control produced one golem per route. With the mod installed, both routes produced zero across 700 world ticks, including seven observed eligible panic checks. Control and enabled fixtures both passed with Minecraft 26.3, Fabric Loader 0.20.1 and Java 25.0.5+8.
