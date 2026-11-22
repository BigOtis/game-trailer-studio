using UnrealBuildTool;

public class TrailerStudio : ModuleRules
{
    public TrailerStudio(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new[] {
            "Json", "JsonUtilities", "Slate", "SlateCore", "InputCore", "ApplicationCore",
            "MovieSceneCapture", "AudioMixer", "RenderCore", "RHI", "Projects"
        });
    }
}
