package dev.sqeedys.no_village_golems_fixture.mixin;

import dev.sqeedys.no_village_golems_fixture.Fixture;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.function.BooleanSupplier;
import net.minecraft.server.MinecraftServer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(MinecraftServer.class)
abstract class FixtureMixin {
    @Unique private Fixture sqeedys$fixture;
    @Unique private boolean sqeedys$finished;

    @Inject(method = "tickServer", at = @At("TAIL"), require = 1, allow = 1)
    private void sqeedys$runFixture(BooleanSupplier hasTime, CallbackInfo callback) throws Exception {
        String mode = System.getProperty("dev.sqeedys.fixture");
        if (sqeedys$finished || mode == null) {
            return;
        }
        MinecraftServer server = (MinecraftServer) (Object) this;
        if (sqeedys$fixture == null) {
            sqeedys$fixture = new Fixture();
        }
        String result = sqeedys$fixture.tick(server, mode.equals("enabled"));
        if (result != null) {
            sqeedys$finished = true;
            Files.writeString(Path.of("receipt.txt"), "PASS " + mode + "\n" + result);
            server.halt(false);
        }
    }
}
