package dev.sqeedys.no_village_golems;

import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.entity.npc.villager.Villager;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(Villager.class)
abstract class VillagerMixin {
    @Inject(method = "spawnGolemIfNeeded", at = @At("HEAD"), cancellable = true, require = 1, allow = 1)
    private void sqeedys$suppressVillageSummon(ServerLevel level, long gameTime, int requiredVillagers, CallbackInfo callback) {
        callback.cancel();
    }
}
