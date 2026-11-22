#include "TrailerStudioSubsystem.h"
#include "Async/Async.h"
#include "AudioDeviceManager.h"
#include "AudioMixerBlueprintLibrary.h"
#include "AudioMixerDevice.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Containers/Queue.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "FrameGrabber.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "InputCoreTypes.h"
#include "InputKeyEventArgs.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "RenderingThread.h"
#include "Runtime/Launch/Resources/Version.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Slate/SceneViewport.h"
#include "Sound/SoundWaveProcedural.h"
#include <atomic>

namespace
{
bool ValidId(const FString &Value)
{
    if (Value.IsEmpty() || Value.Len() > 80)
        return false;
    for (TCHAR C : Value)
        if (!FChar::IsAlnum(C) && C != '_' && C != '-')
            return false;
    return true;
}
TSharedPtr<FJsonObject> Parse(const FString &Text)
{
    TSharedPtr<FJsonObject> O;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), O))
        return nullptr;
    return O;
}
FString Json(const TSharedPtr<FJsonObject> &O)
{
    FString Text;
    FJsonSerializer::Serialize(O.ToSharedRef(), TJsonWriterFactory<>::Create(&Text));
    return Text;
}
void Save(const FString &Path, const TSharedPtr<FJsonObject> &O)
{
    const FString Temp = Path + TEXT(".tmp");
    if (FFileHelper::SaveStringToFile(Json(O), *Temp, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
        IFileManager::Get().Move(*Path, *Temp, true, true);
}
FString Str(const TSharedPtr<FJsonObject> &O, const TCHAR *Key, const FString &Default = FString())
{
    FString V;
    return O.IsValid() && O->TryGetStringField(Key, V) ? V : Default;
}
double Num(const TSharedPtr<FJsonObject> &O, const TCHAR *Key, double Default = 0)
{
    double V;
    return O.IsValid() && O->TryGetNumberField(Key, V) && FMath::IsFinite(V) ? V : Default;
}
TSharedPtr<FJsonObject> Object(const TSharedPtr<FJsonObject> &O, const TCHAR *Key)
{
    const TSharedPtr<FJsonObject> *V = nullptr;
    return O.IsValid() && O->TryGetObjectField(Key, V) ? *V : MakeShared<FJsonObject>();
}
FVector Vector(const TSharedPtr<FJsonObject> &O, FVector Default = FVector::ZeroVector)
{
    return FVector(Num(O, TEXT("x"), Default.X), Num(O, TEXT("y"), Default.Y), Num(O, TEXT("z"), Default.Z));
}
FRotator Rotation(const TSharedPtr<FJsonObject> &O, FRotator Default = FRotator::ZeroRotator)
{
    return FRotator(Num(O, TEXT("pitch"), Default.Pitch), Num(O, TEXT("yaw"), Default.Yaw),
                    Num(O, TEXT("roll"), Default.Roll));
}
TSharedPtr<FJsonObject> Vec(FVector V)
{
    auto O = MakeShared<FJsonObject>();
    O->SetNumberField(TEXT("x"), V.X);
    O->SetNumberField(TEXT("y"), V.Y);
    O->SetNumberField(TEXT("z"), V.Z);
    return O;
}
struct FStudioFrameTime : IFramePayload
{
    double At;
    explicit FStudioFrameTime(double In) : At(In) {}
};
struct FPacket
{
    TArray<FColor> Pixels;
    double At;
};
} // namespace

/** Owns only a viewport observer, a bounded queue, a child encoder and the recording submix. */
class FStudioRecorder
{
  public:
    TWeakObjectPtr<UTrailerStudioSubsystem> Owner;
    TUniquePtr<FFrameGrabber> Grabber;
    TQueue<TUniquePtr<FPacket>, EQueueMode::Spsc> Queue;
    TFuture<void> Writer;
    std::atomic<int32> Queued{0};
    std::atomic<int64> Written{0};
    std::atomic<bool> Done{false}, Failed{false};
    void *InRead = nullptr;
    void *InWrite = nullptr;
    void *OutRead = nullptr;
    void *OutWrite = nullptr;
    FProcHandle Encoder;
    FString Folder, Name, Log, StartedUtc;
    int32 Width = 0, Height = 0, FPS = 30;
    int64 Captured = 0;
    double Started = 0, Stopped = 0, FirstFrame = -1;
    float Unfocused = 0;
    bool Active = false;

    bool Start(UTrailerStudioSubsystem *Context, const FString &Root, const FString &Id, const FString &Exe,
               int32 Rate, const FString &Codec, FString &Error)
    {
        if (!ValidId(Id) || !FPaths::FileExists(Exe) || Exe.Contains(TEXT("\"")))
        {
            Error = TEXT("Invalid take ID or FFmpeg path");
            return false;
        }
        if (!GEngine || !GEngine->GameViewport)
        {
            Error = TEXT("No rendered game viewport");
            return false;
        }
        auto Widget = GEngine->GameViewport->GetGameViewportWidget();
        auto View =
            Widget ? StaticCastSharedPtr<FSceneViewport>(Widget->GetViewportInterface().Pin()) : nullptr;
        if (!View)
        {
            Error = TEXT("No scene viewport");
            return false;
        }
        Width = View->GetSize().X;
        Height = View->GetSize().Y;
        if (Width < 128 || Height < 128 || Width % 2 || Height % 2)
        {
            Error = TEXT("Viewport needs even dimensions >=128");
            return false;
        }
        Folder = FPaths::ConvertRelativePathToFull(Root / Id);
        if (IFileManager::Get().DirectoryExists(*Folder))
        {
            Error = TEXT("Take exists; use a new ID");
            return false;
        }
        IFileManager::Get().MakeDirectory(*Folder, true);
        Name = Id;
        FPS = Rate;
        Owner = Context;
        FPlatformProcess::CreatePipe(InRead, InWrite, true);
        FPlatformProcess::CreatePipe(OutRead, OutWrite, false);
        const FString Encoding = Codec == TEXT("h264_nvenc")
                                     ? TEXT("-c:v h264_nvenc -preset p5 -cq 16")
                                     : TEXT("-c:v libx264 -preset veryfast -crf 16 -threads 2");
        const FString Args = FString::Printf(
            TEXT("-hide_banner -loglevel warning -n -f rawvideo -pixel_format bgra -video_size %dx%d "
                 "-framerate %d -i pipe:0 -an %s -pix_fmt yuv420p -movflags +faststart \"%s\""),
            Width, Height, FPS, *Encoding, *(Folder / TEXT("video.mp4")));
        Encoder = FPlatformProcess::CreateProc(*Exe, *Args, false, true, true, nullptr, 0, nullptr, OutWrite,
                                               InRead, OutWrite);
        if (!Encoder.IsValid())
        {
            Error = TEXT("FFmpeg process could not start");
            Close();
            return false;
        }
        FPlatformProcess::ClosePipe(InRead, nullptr);
        InRead = nullptr;
        FPlatformProcess::ClosePipe(nullptr, OutWrite);
        OutWrite = nullptr;
        Started = FPlatformTime::Seconds();
        StartedUtc = FDateTime::UtcNow().ToIso8601();
        Unfocused = FApp::GetUnfocusedVolumeMultiplier();
        FApp::SetUnfocusedVolumeMultiplier(1);
        UAudioMixerBlueprintLibrary::StartRecordingOutput(Context, 60);
        Grabber = MakeUnique<FFrameGrabber>(View.ToSharedRef(), FIntPoint(Width, Height), PF_B8G8R8A8, 2);
        Grabber->StartCapturingFrames();
        Active = true;
        Writer = Async(EAsyncExecution::Thread, [this]() {
            TArray<FColor> Last;
            auto Write = [this](const TArray<FColor> &Pixels) {
                if (Failed)
                    return;
                int32 Count = 0;
                const int32 Bytes = Pixels.Num() * sizeof(FColor);
                if (!FPlatformProcess::WritePipe(InWrite, reinterpret_cast<const uint8 *>(Pixels.GetData()),
                                                 Bytes, &Count) ||
                    Count != Bytes)
                    Failed = true;
                else
                    ++Written;
            };
            while (!Done || Queued > 0)
            {
                TUniquePtr<FPacket> P;
                if (Queue.Dequeue(P))
                {
                    --Queued;
                    if (Last.IsEmpty())
                        Last = P->Pixels;
                    const int64 Target = FMath::Max<int64>(0, FMath::RoundToInt64(P->At * FPS));
                    while (Written < Target && !Failed)
                        Write(Last);
                    Last = MoveTemp(P->Pixels);
                    if (Written <= Target && !Failed)
                        Write(Last);
                }
                else
                    FPlatformProcess::SleepNoStats(.001f);
            }
            if (!Last.IsEmpty())
                while (Written < FMath::CeilToInt64((Stopped - Started) * FPS) && !Failed)
                    Write(Last);
        });
        Mark(TEXT("capture_start"));
        return true;
    }
    void Mark(const FString &Label)
    {
        auto O = MakeShared<FJsonObject>();
        O->SetStringField(TEXT("utc"), FDateTime::UtcNow().ToIso8601());
        O->SetNumberField(TEXT("seconds"), FPlatformTime::Seconds() - Started);
        O->SetStringField(TEXT("label"), Label);
        FFileHelper::SaveStringToFile(Json(O) + TEXT("\n"), *(Folder / TEXT("events.jsonl")),
                                      FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,
                                      &IFileManager::Get(), FILEWRITE_Append);
    }
    void Drain()
    {
        if (!Grabber)
            return;
        for (auto &Frame : Grabber->GetCapturedFrames())
        {
            auto P = MakeUnique<FPacket>();
            P->At = Frame.GetPayload<FStudioFrameTime>()->At;
            if (FirstFrame < 0)
                FirstFrame = P->At;
            P->Pixels = MoveTemp(Frame.ColorBuffer);
            ++Queued;
            ++Captured;
            Queue.Enqueue(MoveTemp(P));
        }
    }
    void Tick()
    {
        if (!Active)
            return;
        Drain();
        Log += FPlatformProcess::ReadPipe(OutRead);
        if (Queued < 3 && !Failed)
            Grabber->CaptureThisFrame(
                MakeShared<FStudioFrameTime, ESPMode::ThreadSafe>(FPlatformTime::Seconds() - Started));
    }
    void Close()
    {
        FPlatformProcess::ClosePipe(InRead, InWrite);
        InRead = InWrite = nullptr;
        FPlatformProcess::ClosePipe(OutRead, OutWrite);
        OutRead = OutWrite = nullptr;
    }
    void Stop()
    {
        if (!Active)
            return;
        Active = false;
        Stopped = FPlatformTime::Seconds();
        Mark(TEXT("capture_stop"));
        bool AudioWritten = false;
        // Use the stock mixer API and write our own PCM WAV. Blueprint WAV path
        // restrictions vary across engine versions; no modified-engine API is required.
        if (Owner.IsValid())
            if (auto *Mixer = FAudioDeviceManager::GetAudioMixerDeviceFromWorldContext(Owner.Get()))
            {
                float Channels = 0, Rate = 0;
                auto &Samples = Mixer->StopRecording(nullptr, Channels, Rate);
                if (Samples.Num() > 0 && Channels > 0 && Rate > 0)
                {
                    TArray<uint8> Wav;
                    Wav.Reserve(44 + Samples.Num() * 2);
                    auto U16 = [&](uint16 V) {
                        Wav.Add(uint8(V));
                        Wav.Add(uint8(V >> 8));
                    };
                    auto U32 = [&](uint32 V) {
                        for (int32 I = 0; I < 4; ++I)
                            Wav.Add(uint8(V >> (I * 8)));
                    };
                    auto Tag = [&](const char *V) {
                        for (int32 I = 0; I < 4; ++I)
                            Wav.Add(uint8(V[I]));
                    };
                    const uint32 Bytes = Samples.Num() * 2;
                    const uint16 Count = uint16(Channels);
                    Tag("RIFF");
                    U32(36 + Bytes);
                    Tag("WAVE");
                    Tag("fmt ");
                    U32(16);
                    U16(1);
                    U16(Count);
                    U32(uint32(Rate));
                    U32(uint32(Rate) * Count * 2);
                    U16(Count * 2);
                    U16(16);
                    Tag("data");
                    U32(Bytes);
                    for (float Sample : Samples)
                        U16(uint16(int16(FMath::RoundToInt(FMath::Clamp(Sample, -1.f, 1.f) * 32767.f))));
                    AudioWritten = FFileHelper::SaveArrayToFile(Wav, *(Folder / TEXT("audio.wav")));
                }
            }
        FApp::SetUnfocusedVolumeMultiplier(Unfocused);
        Grabber->StopCapturingFrames();
        FlushRenderingCommands();
        Drain();
        Grabber->Shutdown();
        Drain();
        Grabber.Reset();
        Done = true;
        double Deadline = FPlatformTime::Seconds() + 20;
        while (Writer.IsValid() && !Writer.IsReady() && FPlatformTime::Seconds() < Deadline)
        {
            Log += FPlatformProcess::ReadPipe(OutRead);
            FPlatformProcess::SleepNoStats(.01f);
        }
        if (Writer.IsValid() && !Writer.IsReady())
        {
            Failed = true;
            FPlatformProcess::TerminateProc(Encoder, true);
        }
        if (Writer.IsValid())
            Writer.Wait();
        FPlatformProcess::ClosePipe(nullptr, InWrite);
        InWrite = nullptr;
        Deadline = FPlatformTime::Seconds() + 15;
        while (FPlatformProcess::IsProcRunning(Encoder) && FPlatformTime::Seconds() < Deadline)
        {
            Log += FPlatformProcess::ReadPipe(OutRead);
            FPlatformProcess::SleepNoStats(.01f);
        }
        if (FPlatformProcess::IsProcRunning(Encoder))
        {
            Failed = true;
            FPlatformProcess::TerminateProc(Encoder, true);
        }
        int32 Code = -1;
        FPlatformProcess::GetProcReturnCode(Encoder, &Code);
        Log += FPlatformProcess::ReadPipe(OutRead);
        FPlatformProcess::CloseProc(Encoder);
        Close();
        auto O = MakeShared<FJsonObject>();
        O->SetStringField(TEXT("id"), Name);
        O->SetStringField(TEXT("started_utc"), StartedUtc);
        O->SetNumberField(TEXT("width"), Width);
        O->SetNumberField(TEXT("height"), Height);
        O->SetNumberField(TEXT("fps"), FPS);
        O->SetNumberField(TEXT("wall_seconds"), Stopped - Started);
        O->SetNumberField(TEXT("captured_frames"), Captured);
        O->SetNumberField(TEXT("encoded_frames"), double(Written));
        O->SetNumberField(TEXT("first_frame_seconds"), FirstFrame);
        O->SetNumberField(TEXT("encoder_exit"), Code);
        O->SetBoolField(TEXT("audio_written"), AudioWritten);
        O->SetBoolField(TEXT("passed"), !Failed && Code == 0 && Captured > 0 && AudioWritten);
        O->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
        O->SetStringField(TEXT("source"),
                          TEXT("Real-time viewport and master submix; CFR repeats frames when needed; no "
                               "motion interpolation or simulation-speed changes."));
        Save(Folder / TEXT("capture.json"), O);
        FFileHelper::SaveStringToFile(Log, *(Folder / TEXT("encoder.log")));
    }
    ~FStudioRecorder()
    {
        Stop();
        Close();
    }
};

void FStudioRecorderDeleter::operator()(FStudioRecorder *Value) const
{
    delete Value;
}
UTrailerStudioSubsystem::~UTrailerStudioSubsystem() = default;
void UTrailerStudioSubsystem::Initialize(FSubsystemCollectionBase &Collection)
{
    Super::Initialize(Collection);
#if !UE_BUILD_SHIPPING && !UE_BUILD_TEST
    bEnabled = FParse::Param(FCommandLine::Get(), TEXT("TrailerStudio"));
#endif
    if (!bEnabled)
        return;
    FParse::Value(FCommandLine::Get(), TEXT("TrailerSession="), Session);
    FParse::Value(FCommandLine::Get(), TEXT("TrailerBridgeDir="), Bridge);
    FParse::Value(FCommandLine::Get(), TEXT("TrailerOutput="), Output);
    FParse::Value(FCommandLine::Get(), TEXT("TrailerFFmpeg="), FFmpeg);
    FParse::Value(FCommandLine::Get(), TEXT("TrailerCodec="), Codec);
    FParse::Value(FCommandLine::Get(), TEXT("TrailerFPS="), FPS);
    FPS = FMath::Clamp(FPS, 1, 120);
    bDemo = FParse::Param(FCommandLine::Get(), TEXT("TrailerDemo"));
    if (!ValidId(Session) || Bridge.IsEmpty() || Output.IsEmpty())
    {
        bEnabled = false;
        return;
    }
    Bridge = FPaths::ConvertRelativePathToFull(Bridge);
    Output = FPaths::ConvertRelativePathToFull(Output);
    IFileManager::Get().MakeDirectory(*(Bridge / TEXT("inbox")), true);
    IFileManager::Get().MakeDirectory(*(Bridge / TEXT("outbox")), true);
    ProjectState = MakeShared<FJsonObject>();
}
void UTrailerStudioSubsystem::Deinitialize()
{
    StopRecording();
    RestoreCamera();
    bEnabled = false;
    Super::Deinitialize();
}
bool UTrailerStudioSubsystem::IsTickable() const
{
    return bEnabled && !IsTemplate();
}
TStatId UTrailerStudioSubsystem::GetStatId() const
{
    RETURN_QUICK_DECLARE_CYCLE_STAT(UTrailerStudioSubsystem, STATGROUP_Tickables);
}
bool UTrailerStudioSubsystem::SetProjectStateJson(const FString &Text)
{
    auto O = Parse(Text);
    if (!O)
        return false;
    ObserveWorld(GetWorld());
    ProjectState = O;
    return true;
}
void UTrailerStudioSubsystem::RegisterSubject(const FString &Id, AActor *Actor)
{
    if (bEnabled && ValidId(Id) && IsValid(Actor))
    {
        ObserveWorld(Actor->GetWorld());
        Subjects.Add(Id, Actor);
    }
}
void UTrailerStudioSubsystem::Mark(const FString &Label)
{
    if (Recorder)
        Recorder->Mark(Label);
}
void UTrailerStudioSubsystem::StopRecording()
{
    if (Recorder)
    {
        Recorder->Stop();
        Recorder.Reset();
    }
}
bool UTrailerStudioSubsystem::EnsureCamera()
{
    if (Camera.IsValid())
        return true;
    auto *PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
    if (!PC)
        return false;
    PreviousView = PC->GetViewTarget();
    auto *C = GetWorld()->SpawnActor<ACameraActor>();
    if (!C)
        return false;
    Camera = C;
    FVector Location;
    FRotator Aim;
    PC->GetPlayerViewPoint(Location, Aim);
    C->SetActorLocationAndRotation(Location, Aim);
    PC->SetViewTarget(C);
    return true;
}
void UTrailerStudioSubsystem::RestoreCamera()
{
    if (auto *PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr)
        if (PreviousView.IsValid())
            PC->SetViewTarget(PreviousView.Get());
    if (Camera.IsValid())
        Camera->Destroy();
    Camera.Reset();
    PreviousView.Reset();
    MoveSeconds = 0;
    Track.Reset();
}
void UTrailerStudioSubsystem::ScanSubjects()
{
    if (!GetWorld())
        return;
    for (TActorIterator<AActor> A(GetWorld()); A; ++A)
        for (FName Tag : A->Tags)
        {
            const FString Name = Tag.ToString();
            if (Name.StartsWith(TEXT("TrailerSubject:")))
                RegisterSubject(Name.Mid(15), *A);
        }
}
void UTrailerStudioSubsystem::ObserveWorld(UWorld *World)
{
    if (!World || ActiveWorld.Get() == World)
        return;
    StopRecording();
    RestoreCamera();
    Subjects.Empty();
    ActiveWorld = World;
    ProjectState = MakeShared<FJsonObject>();
    bDemoInstalled = false;
    ScanSubjects();
}
void UTrailerStudioSubsystem::Tick(float)
{
    if (ExitAt > 0 && FPlatformTime::Seconds() > ExitAt)
    {
        FPlatformMisc::RequestExit(false);
        return;
    }
    UWorld *World = GetWorld();
    if (!World || World->WorldType != EWorldType::Game || !World->HasBegunPlay())
        return;
    ObserveWorld(World);
    if (bDemo && !bDemoInstalled)
        InstallDemo();
    if (Camera.IsValid() && MoveSeconds > 0)
    {
        const double Alpha = FMath::Clamp((FPlatformTime::Seconds() - MoveAt) / MoveSeconds, 0., 1.);
        const double Ease = Alpha * Alpha * (3. - 2. * Alpha);
        Camera->SetActorLocation(FMath::Lerp(MoveFrom, MoveTo, Ease));
        const FRotator Aim =
            Track.IsValid()
                ? (Track->GetActorLocation() - Camera->GetActorLocation()).Rotation()
                : FQuat::Slerp(RotationFrom.Quaternion(), RotationTo.Quaternion(), Ease).Rotator();
        Camera->SetActorRotation(Aim);
        if (Alpha >= 1)
            MoveSeconds = 0;
    }
    if (Recorder)
        Recorder->Tick();
    const double Now = FPlatformTime::Seconds();
    if (Now < NextPoll)
        return;
    NextPoll = Now + .05;
    Poll();
    PublishState();
}
void UTrailerStudioSubsystem::PublishState()
{
    auto O = MakeShared<FJsonObject>();
    O->SetNumberField(TEXT("version"), 1);
    O->SetStringField(TEXT("session"), Session);
    O->SetNumberField(TEXT("pid"), FPlatformProcess::GetCurrentProcessId());
    O->SetBoolField(TEXT("ready"), true);
    O->SetStringField(TEXT("map"), GetWorld()->GetMapName());
    O->SetNumberField(TEXT("world_seconds"), GetWorld()->GetTimeSeconds());
    O->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    auto C = MakeShared<FJsonObject>();
    C->SetBoolField(TEXT("active"), Camera.IsValid());
    C->SetBoolField(TEXT("moving"), MoveSeconds > 0);
    if (Camera.IsValid())
        C->SetObjectField(TEXT("location"), Vec(Camera->GetActorLocation()));
    O->SetObjectField(TEXT("camera"), C);
    auto R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("active"), Recorder && Recorder->Active);
    if (Recorder)
    {
        R->SetStringField(TEXT("take"), Recorder->Name);
        R->SetNumberField(TEXT("frames"), double(Recorder->Written));
    }
    O->SetObjectField(TEXT("recording"), R);
    O->SetObjectField(TEXT("project"), ProjectState.IsValid() ? ProjectState : MakeShared<FJsonObject>());
    auto S = MakeShared<FJsonObject>();
    for (const auto &Pair : Subjects)
        if (Pair.Value.IsValid())
        {
            auto Item = MakeShared<FJsonObject>();
            Item->SetObjectField(TEXT("location"), Vec(Pair.Value->GetActorLocation()));
            S->SetObjectField(Pair.Key, Item);
        }
    O->SetObjectField(TEXT("subjects"), S);
    Save(Bridge / TEXT("state.json"), O);
}
void UTrailerStudioSubsystem::Poll()
{
    TArray<FString> Files;
    IFileManager::Get().FindFiles(Files, *(Bridge / TEXT("inbox/*.json")), true, false);
    Files.Sort();
    if (Files.IsEmpty())
        return;
    const FString Path = Bridge / TEXT("inbox") / Files[0];
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *Path))
        return;
    IFileManager::Get().Delete(*Path);
    auto Request = Parse(Text);
    if (!Request)
        return;
    const FString Id = Str(Request, TEXT("id"));
    FGuid Guid;
    if (!FGuid::Parse(Id, Guid))
        return;
    auto Response = MakeShared<FJsonObject>();
    Response->SetStringField(TEXT("id"), Id);
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    FString Error;
    bool OK = false;
    if (Num(Request, TEXT("version")) != 1 || Str(Request, TEXT("session")) != Session ||
        Num(Request, TEXT("expected_pid")) != FPlatformProcess::GetCurrentProcessId())
        Error = TEXT("Session, process or protocol mismatch");
    else
        OK = Execute(Request, Result, Error);
    Response->SetBoolField(TEXT("ok"), OK);
    Response->SetStringField(TEXT("error"), Error);
    Response->SetObjectField(TEXT("result"), Result);
    PublishState();
    Save(Bridge / TEXT("outbox") / (Id + TEXT(".json")), Response);
}
bool UTrailerStudioSubsystem::Execute(const TSharedPtr<FJsonObject> &Request, TSharedPtr<FJsonObject> &Result,
                                      FString &Error)
{
    const FString Type = Str(Request, TEXT("command"));
    auto A = Object(Request, TEXT("arguments"));
    Mark(TEXT("command:") + Type);
    if (Type == TEXT("ping"))
        return true;
    if (Type == TEXT("shutdown"))
    {
        StopRecording();
        ExitAt = FPlatformTime::Seconds() + .2;
        return true;
    }
    if (Type == TEXT("mark"))
    {
        Mark(Str(A, TEXT("label")));
        return true;
    }
    if (Type == TEXT("capture_start"))
    {
        if (Recorder)
        {
            Error = TEXT("A recording is already active");
            return false;
        }
        TUniquePtr<FStudioRecorder, FStudioRecorderDeleter> R(new FStudioRecorder());
        if (!R->Start(this, Output, Str(A, TEXT("take")), FFmpeg, FPS, Codec, Error))
            return false;
        Recorder = MoveTemp(R);
        return true;
    }
    if (Type == TEXT("capture_stop"))
    {
        StopRecording();
        return true;
    }
    if (Type == TEXT("subjects_refresh"))
    {
        ScanSubjects();
        return true;
    }
    if (Type == TEXT("camera_restore"))
    {
        RestoreCamera();
        return true;
    }
    if (Type == TEXT("camera_set") || Type == TEXT("camera_move"))
    {
        const FString TrackId = Str(A, TEXT("track"));
        const auto RequestedTrack = Subjects.FindRef(TrackId);
        if (!TrackId.IsEmpty() && !RequestedTrack.IsValid())
        {
            Error = TEXT("Unknown tracking subject; register it first");
            return false;
        }
        if (!EnsureCamera())
        {
            Error = TEXT("No local player controller for camera");
            return false;
        }
        MoveSeconds = 0;
        MoveFrom = Camera->GetActorLocation();
        RotationFrom = Camera->GetActorRotation();
        MoveTo = Vector(Object(A, TEXT("location")), MoveFrom);
        RotationTo = Rotation(Object(A, TEXT("rotation")), RotationFrom);
        Camera->GetCameraComponent()->SetFieldOfView(
            FMath::Clamp(Num(A, TEXT("fov"), Camera->GetCameraComponent()->FieldOfView), 20., 140.));
        Track = RequestedTrack;
        if (Type == TEXT("camera_set"))
        {
            Camera->SetActorLocationAndRotation(
                MoveTo, Track.IsValid() ? (Track->GetActorLocation() - MoveTo).Rotation() : RotationTo);
        }
        else
        {
            MoveAt = FPlatformTime::Seconds();
            MoveSeconds = FMath::Clamp(Num(A, TEXT("duration"), 3), .05, 300.);
        }
        return true;
    }
    if (Type == TEXT("actor_set"))
    {
        auto Actor = Subjects.FindRef(Str(A, TEXT("subject")));
        if (!Actor.IsValid())
        {
            Error = TEXT("Unknown subject");
            return false;
        }
        FTransform Pose = Actor->GetActorTransform();
        Pose.SetLocation(Vector(Object(A, TEXT("location")), Pose.GetLocation()));
        Pose.SetRotation(Rotation(Object(A, TEXT("rotation")), Pose.Rotator()).Quaternion());
        Pose.SetScale3D(Vector(Object(A, TEXT("scale")), Pose.GetScale3D()));
        Actor->SetActorTransform(Pose, false, nullptr, ETeleportType::TeleportPhysics);
        TArray<UPrimitiveComponent *> Components;
        Actor->GetComponents(Components);
        for (auto *C : Components)
            if (C->IsSimulatingPhysics())
            {
                C->SetPhysicsLinearVelocity(FVector::ZeroVector);
                C->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
                C->WakeAllRigidBodies();
            }
        return true;
    }
    if (Type == TEXT("key"))
    {
        auto *PC = GetWorld()->GetFirstPlayerController();
        const FKey Key(*Str(A, TEXT("key")));
        if (!PC || !Key.IsValid())
        {
            Error = TEXT("Invalid player/key");
            return false;
        }
        const EInputEvent Event = Str(A, TEXT("event")) == TEXT("release") ? IE_Released : IE_Pressed;
#if ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 6
        PC->InputKey(FInputKeyEventArgs::CreateSimulated(Key, Event, 1.f));
#else
        PC->InputKey(FInputKeyParams(Key, Event, 1.f, false));
#endif
        return true;
    }
    if (Type == TEXT("type_text"))
    {
        if (!FSlateApplication::IsInitialized() ||
            !FSlateApplication::Get().GetKeyboardFocusedWidget().IsValid())
        {
            Error = TEXT("Focus the game's text widget first");
            return false;
        }
        for (TCHAR Ch : Str(A, TEXT("text")))
            FSlateApplication::Get().ProcessKeyCharEvent(FCharacterEvent(Ch, FModifierKeysState(), 0, false));
        bool Commit = false;
        A->TryGetBoolField(TEXT("commit"), Commit);
        if (Commit)
        {
            const FKeyEvent E(EKeys::Enter, FModifierKeysState(), 0, false, 0, 0);
            FSlateApplication::Get().ProcessKeyDownEvent(E);
            FSlateApplication::Get().ProcessKeyUpEvent(E);
        }
        return true;
    }
    if (Type == TEXT("project"))
    {
        if (!OnProjectCommand.IsBound())
        {
            Error = TEXT("No project-command hook is bound; implement your game's handler");
            return false;
        }
        OnProjectCommand.Broadcast(Str(A, TEXT("name")), Json(Object(A, TEXT("payload"))));
        Result->SetBoolField(TEXT("dispatched"), true);
        return true;
    }
    if (Type == TEXT("demo_tone") && bDemo)
    {
        DemoSound = NewObject<USoundWaveProcedural>(this);
        DemoSound->SetSampleRate(48000);
        DemoSound->NumChannels = 1;
        DemoSound->Duration = 6;
        TArray<int16> PCM;
        PCM.SetNum(48000 * 6);
        for (int32 I = 0; I < PCM.Num(); ++I)
            PCM[I] = int16(FMath::Sin(2 * PI * 440 * I / 48000.) * 3500);
        DemoSound->QueueAudio(reinterpret_cast<const uint8 *>(PCM.GetData()), PCM.Num() * sizeof(int16));
        UGameplayStatics::PlaySound2D(this, DemoSound);
        return true;
    }
    Error = TEXT("Unknown or unavailable command");
    return false;
}
void UTrailerStudioSubsystem::InstallDemo()
{
    bDemoInstalled = true;
    UWorld *W = GetWorld();
    if (auto *PC = W->GetFirstPlayerController())
        if (APawn *Pawn = PC->GetPawn())
            Pawn->SetActorHiddenInGame(true);
    auto Spawn = [&](const TCHAR *Id, const TCHAR *Mesh, FVector At, FVector Scale, bool Physics) {
        auto *A = W->SpawnActor<AStaticMeshActor>();
        auto *C = A->GetStaticMeshComponent();
        C->SetMobility(EComponentMobility::Movable);
        C->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, Mesh));
        A->SetActorLocation(At);
        A->SetActorScale3D(Scale);
        C->SetCollisionProfileName(TEXT("BlockAllDynamic"));
        C->SetSimulatePhysics(Physics);
        RegisterSubject(Id, A);
        return A;
    };
    Spawn(TEXT("floor"), TEXT("/Engine/BasicShapes/Cube.Cube"), FVector(0, 0, -30), FVector(14, 14, .5),
          false);
    Spawn(TEXT("cube"), TEXT("/Engine/BasicShapes/Cube.Cube"), FVector(0, 0, 60), FVector(1), false);
    Spawn(TEXT("ball"), TEXT("/Engine/BasicShapes/Sphere.Sphere"), FVector(0, 140, 400), FVector(.7), true);
    auto *Light = W->SpawnActor<ADirectionalLight>();
    Light->SetActorRotation(FRotator(-45, -30, 0));
    Light->GetLightComponent()->SetIntensity(5);
    if (EnsureCamera())
        Camera->SetActorLocationAndRotation(FVector(-600, -600, 280),
                                            (FVector(0, 0, 70) - FVector(-600, -600, 280)).Rotation());
}
