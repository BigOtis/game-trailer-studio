#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Tickable.h"
#include "TrailerStudioSubsystem.generated.h"

class ACameraActor;
class FStudioRecorder;
struct FStudioRecorderDeleter
{
    void operator()(FStudioRecorder *Value) const;
};
class USoundWaveProcedural;
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnTrailerProjectCommand, const FString &, Name, const FString &,
                                             ArgumentsJson);

/** Local opt-in Development tooling. No networking, arbitrary console execution or model dependencies. */
UCLASS()
class TRAILERSTUDIO_API UTrailerStudioSubsystem : public UGameInstanceSubsystem, public FTickableGameObject
{
    GENERATED_BODY()
  public:
    virtual ~UTrailerStudioSubsystem() override;
    virtual void Initialize(FSubsystemCollectionBase &Collection) override;
    virtual void Deinitialize() override;
    virtual void Tick(float DeltaTime) override;
    virtual bool IsTickable() const override;
    virtual bool IsTickableWhenPaused() const override
    {
        return true;
    }
    virtual TStatId GetStatId() const override;
    /** Bind in the capture-only integration actor. Publish observed state with SetProjectStateJson. */
    UPROPERTY(BlueprintAssignable, Category = "Trailer Studio") FOnTrailerProjectCommand OnProjectCommand;
    UFUNCTION(BlueprintPure, Category = "Trailer Studio") bool IsEnabled() const
    {
        return bEnabled;
    }
    UFUNCTION(BlueprintCallable, Category = "Trailer Studio") bool SetProjectStateJson(const FString &Json);
    UFUNCTION(BlueprintCallable, Category = "Trailer Studio")
    void RegisterSubject(const FString &Id, AActor *Actor);
    UFUNCTION(BlueprintCallable, Category = "Trailer Studio") void Mark(const FString &Label);

  private:
    bool bEnabled = false, bDemo = false, bDemoInstalled = false;
    FString Session, Bridge, Output, FFmpeg, Codec;
    int32 FPS = 30;
    double NextPoll = 0, MoveAt = 0, MoveSeconds = 0, ExitAt = 0;
    FVector MoveFrom, MoveTo;
    FRotator RotationFrom, RotationTo;
    TWeakObjectPtr<AActor> Track, PreviousView;
    TWeakObjectPtr<ACameraActor> Camera;
    TWeakObjectPtr<UWorld> ActiveWorld;
    TMap<FString, TWeakObjectPtr<AActor>> Subjects;
    TSharedPtr<class FJsonObject> ProjectState;
    TUniquePtr<FStudioRecorder, FStudioRecorderDeleter> Recorder;
    UPROPERTY() TObjectPtr<USoundWaveProcedural> DemoSound;
    bool EnsureCamera();
    void RestoreCamera();
    void ScanSubjects();
    void InstallDemo();
    void ObserveWorld(UWorld *World);
    void StopRecording();
    void PublishState();
    void Poll();
    bool Execute(const TSharedPtr<FJsonObject> &Command, TSharedPtr<FJsonObject> &Result, FString &Error);
};
