package dev.sqeedys.no_village_golems_fixture;

import com.mojang.authlib.GameProfile;
import java.util.List;
import java.util.UUID;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ClientInformation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.EntitySpawnReason;
import net.minecraft.world.entity.EntityTypes;
import net.minecraft.world.entity.animal.golem.IronGolem;
import net.minecraft.world.entity.ai.memory.MemoryModuleType;
import net.minecraft.world.entity.monster.zombie.Zombie;
import net.minecraft.world.entity.npc.villager.Villager;
import net.minecraft.world.entity.schedule.Activity;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.network.Connection;
import net.minecraft.network.protocol.PacketFlow;
import net.minecraft.server.network.CommonListenerCookie;
import net.minecraft.server.network.ServerGamePacketListenerImpl;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;

public final class Fixture {
    private static final int TEST_TICKS = 700;
    private BlockPos panicSite;
    private long deadline;
    private int panicOpportunityTicks;
    private IronGolem existing;
    private IronGolem constructed;
    private List<Villager> panicking;
    private int gossipSummons;
    private int panicSummons;

    public String tick(MinecraftServer server, boolean enabled) {
        ServerLevel level = server.overworld();
        if (deadline == 0) {
            int y = level.getMinY() + 4;
            panicSite = new BlockPos(8, y, 8);
            BlockPos gossipSite = new BlockPos(56, y, 8);
            BlockPos construction = new BlockPos(88, y, 8);
            BlockPos existingSite = new BlockPos(104, y, 8);
            for (BlockPos site : List.of(panicSite, gossipSite, construction, existingSite)) {
                level.setChunkForced(site.getX() >> 4, site.getZ() >> 4, true);
            }
            if (List.of(panicSite, gossipSite, construction, existingSite).stream()
                    .anyMatch(site -> !level.isPositionEntityTicking(site))) {
                return null;
            }

            existing = EntityTypes.IRON_GOLEM.spawn(level, existingSite, EntitySpawnReason.COMMAND);
            check(existing != null, "could not directly spawn an iron golem");
            existing.setNoAi(true);

            constructed = construct(server, level, construction);
            Villager first = villager(level, gossipSite, true);
            Villager second = villager(level, gossipSite.offset(2, 0, 0), true);
            for (int i = 2; i < 5; i++) {
                villager(level, gossipSite.offset(i, 0, 2), true);
            }
            // The native gossip clock rejects a new pair until game time exceeds 1,200.
            first.gossip(level, second, level.getGameTime() + 1200);
            gossipSummons = villageGolems(level, gossipSite);
            check(gossipSummons == (enabled ? 0 : 1), "unexpected gossip summon count: " + gossipSummons);

            for (int offset = -3; offset <= 3; offset++) {
                level.setBlockAndUpdate(panicSite.offset(offset, 0, -3), Blocks.OAK_FENCE.defaultBlockState());
                level.setBlockAndUpdate(panicSite.offset(offset, 0, 3), Blocks.OAK_FENCE.defaultBlockState());
                level.setBlockAndUpdate(panicSite.offset(-3, 0, offset), Blocks.OAK_FENCE.defaultBlockState());
                level.setBlockAndUpdate(panicSite.offset(3, 0, offset), Blocks.OAK_FENCE.defaultBlockState());
            }
            panicking = List.of(villager(level, panicSite.offset(-1, 0, 0), false),
                villager(level, panicSite.offset(0, 0, -1), false),
                villager(level, panicSite.offset(1, 0, 1), false));
            Zombie threat = EntityTypes.HUSK.create(level, EntitySpawnReason.COMMAND);
            threat.setPos(Vec3.atBottomCenterOf(panicSite.offset(0, 0, 2)));
            threat.setNoAi(true);
            threat.setPersistenceRequired();
            check(level.addFreshEntity(threat), "could not add the panic stimulus");
            server.tickRateManager().setTickRate(100);
            deadline = level.getGameTime() + TEST_TICKS;
        }
        if (level.getGameTime() % 100 == 0 && panicking.stream().allMatch(villager -> villager.isAlive()
                && villager.getBrain().getActiveNonCoreActivity().orElse(null) == Activity.PANIC
                && villager.wantsToSpawnGolem(level.getGameTime()))) {
            panicOpportunityTicks++;
        }
        if (level.getGameTime() % 100 == 0) {
            panicSummons = Math.max(panicSummons, villageGolems(level, panicSite));
        }
        if (level.getGameTime() < deadline) {
            return null;
        }
        check(enabled ? panicSummons == 0 : panicSummons >= 1,
            "unexpected panic summon count: " + panicSummons + ", eligible panic ticks: " + panicOpportunityTicks);
        if (enabled) {
            check(panicOpportunityTicks > 0, "no eligible native panic tick in the suppression fixture");
        }
        check(level.getEntity(existing.getUUID()) == existing && existing.isAlive() && !existing.isPlayerCreated(),
            "the pre-existing golem changed or disappeared");
        check(level.getEntity(constructed.getUUID()) == constructed && constructed.isAlive() && constructed.isPlayerCreated(),
            "the constructed golem changed or disappeared");
        return "Native panic golems: " + panicSummons + " in " + TEST_TICKS + " ticks.\n"
            + "Eligible panic tick observations without a detected golem: " + panicOpportunityTicks + ".\n"
            + "Native gossip golems: " + gossipSummons + ".\n"
            + "Player-built and pre-existing iron golems both survived.\n";
    }

    private static Villager villager(ServerLevel level, BlockPos pos, boolean stationary) {
        Villager villager = EntityTypes.VILLAGER.create(level, EntitySpawnReason.COMMAND);
        villager.setPos(Vec3.atBottomCenterOf(pos));
        villager.setNoAi(stationary);
        villager.setPersistenceRequired();
        // Seed the native recent-sleep memory so the synthetic fixture starts after a night in beds.
        villager.getBrain().setMemory(MemoryModuleType.LAST_SLEPT, level.getGameTime());
        check(level.addFreshEntity(villager), "could not add the villager");
        return villager;
    }

    private static IronGolem construct(MinecraftServer server, ServerLevel level, BlockPos base) {
        BlockPos shoulders = base.above();
        for (BlockPos iron : List.of(base, shoulders, shoulders.west(), shoulders.east())) {
            check(level.setBlockAndUpdate(iron, Blocks.IRON_BLOCK.defaultBlockState()), "could not place fixture iron");
        }
        GameProfile profile = new GameProfile(UUID.randomUUID(), "GolemTester");
        ServerPlayer player = new ServerPlayer(server, level, profile, ClientInformation.createDefault());
        new ServerGamePacketListenerImpl(server, new Connection(PacketFlow.SERVERBOUND), player,
            CommonListenerCookie.createInitial(profile, false));
        player.setPos(Vec3.atBottomCenterOf(base.south(3)));
        ItemStack pumpkin = new ItemStack(Items.CARVED_PUMPKIN);
        player.setItemInHand(InteractionHand.MAIN_HAND, pumpkin);
        BlockHitResult top = new BlockHitResult(Vec3.atCenterOf(shoulders).add(0, 0.5, 0), Direction.UP, shoulders, false);
        check(player.gameMode.useItemOn(player, level, pumpkin, InteractionHand.MAIN_HAND, top).consumesAction(),
            "the player's pumpkin placement did not succeed");
        List<IronGolem> found = level.getEntitiesOfClass(IronGolem.class, new AABB(base).inflate(3));
        check(found.size() == 1 && found.getFirst().isPlayerCreated(), "the normal player-built golem did not spawn");
        found.getFirst().setNoAi(true);
        return found.getFirst();
    }

    private static int villageGolems(ServerLevel level, BlockPos site) {
        return level.getEntitiesOfClass(IronGolem.class, new AABB(site).inflate(16), golem -> !golem.isPlayerCreated()).size();
    }

    private static void check(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }
}
