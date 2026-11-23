using System.Globalization;
using System.Text.Json;
using System.Xml;
using System.Diagnostics;
using Microsoft.UI;
using Microsoft.UI.Input;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Markup;
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;
using Windows.Graphics;
using Windows.Storage.Pickers;
using Windows.System;
using Windows.UI.Core;

namespace Grain;
public sealed partial class MainWindow : Window
{
    private readonly BackendClient backend=new();
    private readonly HashSet<int> selection=new();
    private List<MeasurementRow> rows=new();
    private List<string> columns=new();
    private JsonElement state;
    private bool busy=true,ready,loaded,dirty,syncing,allowClose,initialized,dividerDragging;
    private string? sortColumn;
    private bool descending;
    private string currentUnit="px";
    private string? savedFolder;
    private string? geometryToken;
    private double dividerY,tableHeight;
    private readonly Stopwatch operationClock=new();
    private DispatcherTimer? progressTimer;
    private WorkProgress? latestProgress;
    private TimeSpan progressReceivedAt;
    private double progressValue;
    private string ChosenVariant=>(string)((ComboBoxItem)ModelChoice.SelectedItem).Tag;
    private string ChosenBackend=>(string)((ComboBoxItem)DeviceChoice.SelectedItem).Tag;
    private readonly IntPtr hwnd;
    private static readonly string[] Preferred={"grain_id","area","major_axis_length","minor_axis_length","perimeter","centroid-0","centroid-1"};

    public MainWindow()
    {
        InitializeComponent();
        hwnd=WinRT.Interop.WindowNative.GetWindowHandle(this);
        ExtendsContentIntoTitleBar=true;SetTitleBar(TitleDrag);
        AppWindow.TitleBar.ButtonBackgroundColor=Colors.Transparent;
        AppWindow.TitleBar.ButtonInactiveBackgroundColor=Colors.Transparent;
        AppWindow.TitleBar.ButtonForegroundColor=Windows.UI.Color.FromArgb(255,34,63,45);
        var work=DisplayArea.GetFromWindowId(AppWindow.Id,DisplayAreaFallback.Primary).WorkArea;
        int width=Math.Min(1480,work.Width-60),height=Math.Min(980,work.Height-60);
        AppWindow.Resize(new SizeInt32(width,height));
        AppWindow.Move(new PointInt32(work.X+(work.Width-width)/2,work.Y+(work.Height-height)/2));
        AppWindow.Changed+=(_,e)=>{if(e.DidSizeChange&&(AppWindow.Size.Width<1120||AppWindow.Size.Height<760))AppWindow.Resize(new SizeInt32(Math.Max(1120,AppWindow.Size.Width),Math.Max(760,AppWindow.Size.Height)));};
        if(File.Exists(Path.Combine(AppContext.BaseDirectory,"Assets","Grain.ico")))AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory,"Assets","Grain.ico"));
        try {SystemBackdrop=new Microsoft.UI.Xaml.Media.MicaBackdrop();}catch{/* Solid fallback on unsupported systems. */}
        Root.Loaded+=async(_,_)=>{if(!initialized){initialized=true;await InitializeAsync();}};
        Root.KeyDown+=Root_KeyDown;
        Closed+=(_,_)=>{progressTimer?.Stop();backend.Dispose();};
        AppWindow.Closing+=async(_,e)=>{
            if(allowClose)return;
            if(busy){e.Cancel=true;ShowNotice("Still processing","Wait for the current operation to finish before closing.",InfoBarSeverity.Informational);return;}
            if(!dirty){allowClose=true;return;}
            e.Cancel=true;
            if(await ConfirmLeavingAsync()){allowClose=true;DispatcherQueue.TryEnqueue(()=>Close());}
        };
        backend.Progress+=update=>{
            if(DispatcherQueue.HasThreadAccess)ShowProgress(update);
            else DispatcherQueue.TryEnqueue(()=>ShowProgress(update));
        };
        Editor.GrainPicked+=(id,ctrl)=>{
            if(busy)return;
            if(!ctrl)selection.Clear();
            if(id is int grain){if(ctrl&&selection.Contains(grain))selection.Remove(grain);else selection.Add(grain);}
            SyncSelection();
        };
        Editor.PointPlaced+=async(x,y,fg)=>{
            if(busy)return;
            if(Editor.Mode=="add")await RunAsync("add",new {points=new[]{new[]{x,y}},labels=new[]{1},variant=ChosenVariant,backend=ChosenBackend},"Finding the grain at your point…","Grain added. You can undo this correction.");
            else ToolHint.Text=$"{Editor.PromptData().points.Length} prompt points · Create from points when ready";
        };
        Editor.RulerDrawn+=async points=>{
            await CalibrateAsync(points);SetTool("select");
        };
        Editor.ZoomChanged+=zoom=>ZoomLabel.Text=$"{zoom*100:0}%";
        UpdateControls();
    }
    private async Task InitializeAsync()
    {
        BeginProgress("Starting the local processing engine…");
        try {
            await backend.StartAsync();ready=true;
            await ApplyStateAsync(await backend.CallAsync("hello"));
            StatusLabel.Text="Ready when you are. Open an image to begin.";
            await CompleteProgressAsync();busy=false;UpdateControls();
            SignalSetupReady();
            string[] args=Environment.GetCommandLineArgs();
            int test=Array.IndexOf(args,"--project");
            if(test>=0&&args.Length>test+1)await RunAsync("open_project",new {path=args[test+1]},"Opening project…","Project opened. Your measurements are ready.");
            int verify=Array.IndexOf(args,"--verify");
            if(verify>=0&&args.Length>verify+1)await VerifyAsync(args[verify+1]);
        }catch(Exception ex){ShowNotice("The engine could not start",ex.Message);StatusLabel.Text="Processing engine unavailable. See the message above.";}
        finally{EndProgress();busy=false;UpdateControls();}
    }
    private void ShowNotice(string title,string message,InfoBarSeverity severity=InfoBarSeverity.Error)
    {
        Notice.Title=title;Notice.Message=message;Notice.Severity=severity;Notice.IsOpen=true;
    }
    private static void SignalSetupReady()
    {
        string? destination=Environment.GetEnvironmentVariable("SEGMENTEVERYGRAIN_READY_FILE");
        if(string.IsNullOrWhiteSpace(destination))return;
        string folder=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SegmentEveryGrainDesktop");
        string path=Path.GetFullPath(destination);
        if(!string.Equals(Path.GetDirectoryName(path),folder,StringComparison.OrdinalIgnoreCase)||
            !Path.GetFileName(path).StartsWith("ready-",StringComparison.Ordinal)||!path.EndsWith(".json",StringComparison.OrdinalIgnoreCase))return;
        File.WriteAllText(path,JsonSerializer.Serialize(new {ready=true,ui="winui3"}));
    }
    private void UpdateControls()
    {
        bool available=ready&&!busy;
        OpenButton.IsEnabled=ProjectButton.IsEnabled=available;
        ModelChoice.IsEnabled=MinimumArea.IsEnabled=DeviceChoice.IsEnabled=available;
        SegmentButton.IsEnabled=ManualButton.IsEnabled=available&&loaded;
        SaveButton.IsEnabled=ExportButton.IsEnabled=available&&loaded;
        SetPanelEnabled(EditTools,available&&loaded);SetPanelEnabled(CalibrationTools,available&&loaded);SetPanelEnabled(CanvasTools,available&&loaded);Editor.IsEnabled=available&&loaded;
        DeleteButton.IsEnabled=available&&selection.Count>0;
        MergeButton.IsEnabled=available&&selection.Count>1;
        UndoButton.IsEnabled=available&&loaded&&state.TryGetProperty("canUndo",out var u)&&u.GetBoolean();
        RedoButton.IsEnabled=available&&loaded&&state.TryGetProperty("canRedo",out var r)&&r.GetBoolean();
        SelectedOnly.IsEnabled=available&&loaded;
        Measurements.IsEnabled=available;
        OperationBar.Visibility=ProgressTiming.Visibility=ProgressElapsed.Visibility=busy?Visibility.Visible:Visibility.Collapsed;
    }
    private void BeginProgress(string message)
    {
        operationClock.Restart();latestProgress=null;progressValue=0;
        OperationBar.Value=0;OperationBar.IsIndeterminate=true;StatusLabel.Text=message;
        progressTimer??=new DispatcherTimer{Interval=TimeSpan.FromMilliseconds(250)};
        if(!progressTimer.IsEnabled){progressTimer.Tick-=ProgressTick;progressTimer.Tick+=ProgressTick;progressTimer.Start();}
        RefreshProgressTiming();
    }
    private void ProgressTick(object? sender,object e)=>RefreshProgressTiming();
    private static string Duration(double seconds)
    {
        int s=(int)Math.Min(int.MaxValue,Math.Max(0,Math.Ceiling(seconds)));
        return s>=3600?$"{s/3600}h {s%3600/60}m":s>=60?$"{s/60}m {s%60}s":$"{s}s";
    }
    private void ShowProgress(WorkProgress update)
    {
        if(!busy||!operationClock.IsRunning)return;
        latestProgress=update;progressReceivedAt=operationClock.Elapsed;
        if(update.Percent is double value)progressValue=Math.Max(progressValue,Math.Clamp(value,0,99.8));
        OperationBar.Value=progressValue;OperationBar.IsIndeterminate=update.Indeterminate;
        StatusLabel.Text=update.Message+(update.Total is >0?$" · {update.Completed??0:N0} / {update.Total:N0}":"");
        RefreshProgressTiming();
    }
    private void RefreshProgressTiming()
    {
        string prefix=latestProgress?.Percent is not null?$"{Math.Floor(progressValue):0}% · ":"";
        if(latestProgress?.RemainingSeconds is double eta) {
            double remaining=eta-(operationClock.Elapsed-progressReceivedAt).TotalSeconds;
            ProgressTiming.Text=prefix+(remaining>0?$"About {Duration(remaining)} left in this stage":"Finishing this stage…");
        }else ProgressTiming.Text=prefix+"Estimating time remaining…";
        ProgressElapsed.Text=$"Elapsed {Duration(operationClock.Elapsed.TotalSeconds)} · Estimates adapt to the current processing stage";
    }
    private async Task CompleteProgressAsync()
    {
        operationClock.Stop();progressTimer?.Stop();OperationBar.IsIndeterminate=false;OperationBar.Value=100;
        ProgressTiming.Text="100% · Complete";
        await Task.Delay(160);
    }
    private void EndProgress(){operationClock.Stop();progressTimer?.Stop();}
    private static void SetPanelEnabled(Panel panel,bool enabled)
    {
        foreach(var child in panel.Children) {
            if(child is Control control)control.IsEnabled=enabled;
            else if(child is Panel nested)SetPanelEnabled(nested,enabled);
        }
    }
    private async Task<bool> RunAsync(string method,object? args,string progress,string success)
    {
        if(busy && method!="open_project")return false;
        busy=true;Notice.IsOpen=false;BeginProgress(progress);UpdateControls();
        try {
            var result=await backend.CallAsync(method,args);
            await ApplyStateAsync(result);StatusLabel.Text=success;
            if(method=="add"){Editor.ClearPrompts();}
            await CompleteProgressAsync();
            return true;
        }catch(Exception ex){ShowNotice("Couldn't complete the operation",ex.Message);StatusLabel.Text="Nothing was discarded. Review the message and try again.";return false;}
        finally{EndProgress();busy=false;UpdateControls();}
    }
    private async Task ApplyStateAsync(JsonElement result)
    {
        state=result;loaded=result.GetProperty("loaded").GetBoolean();
        if(result.TryGetProperty("config",out var config)) {
            string device=config.TryGetProperty("adapter_name",out var name)?name.GetString()??"GPU":"GPU";
            GpuDevice.Content=$"GPU · {device.Replace("AMD Radeon ","")}";
            if(!loaded)DeviceChoice.SelectedIndex=config.GetProperty("backend").GetString()=="directml"?0:1;
        }
        if(!loaded){EmptyState.Visibility=Visibility.Visible;return;}
        EmptyState.Visibility=Visibility.Collapsed;
        dirty=result.GetProperty("dirty").GetBoolean();
        savedFolder=result.GetProperty("project").ValueKind==JsonValueKind.String?result.GetProperty("project").GetString():null;
        string source=result.GetProperty("sourcePath").GetString()!;
        int width=result.GetProperty("width").GetInt32(),height=result.GetProperty("height").GetInt32();
        ImageTitle.Text=Path.GetFileName(source)+(dirty?"  ·  Unsaved changes":"");
        ImageMeta.Text=$"{width:N0} × {height:N0} pixels";
        currentUnit=result.GetProperty("unit").GetString()!;
        rows=result.GetProperty("grains").EnumerateArray().Select(g=>new MeasurementRow(g)).ToList();
        selection.IntersectWith(rows.Select(r=>r.Id));
        ModelChoice.SelectedIndex=result.GetProperty("variant").GetString()=="tiny"?1:0;
        DeviceChoice.SelectedIndex=result.GetProperty("backend").GetString()=="directml"?0:1;
        EngineLabel.Text=(DeviceChoice.SelectedIndex==0?"DIRECTML":"CPU")+"  /  PROCESSED LOCALLY";
        ReferenceLength.Value=result.GetProperty("referenceLength").GetDouble();
        UnitChoice.SelectedIndex=result.GetProperty("calibrationUnit").GetString()=="cm"?1:0;
        bool calibrated=result.GetProperty("pixelsPerMeter").ValueKind==JsonValueKind.Number;
        CalibrationLabel.Text=calibrated?$"Calibrated · {result.GetProperty("pixelsPerMeter").GetDouble()*(currentUnit=="mm"?.001:.01):G5} px / {currentUnit}":"No reference yet · sizes in pixels";
        var ruler=result.GetProperty("ruler");
        await Editor.LoadImageAsync(result.GetProperty("imagePath").GetString()!,width,height);
        string nextGeometry=result.GetProperty("imagePath").GetString()+result.GetProperty("geometryToken").GetString();
        if(nextGeometry!=geometryToken){
            ShowProgress(new WorkProgress("Drawing grain overlays",98,Indeterminate:false));
            var rendering=Stopwatch.StartNew();
            await Editor.SetGeometryAsync(result.GetProperty("grains"),(done,total)=>{
                double? eta=done>0&&rendering.Elapsed.TotalSeconds>=.5?rendering.Elapsed.TotalSeconds/done*(total-done):null;
                ShowProgress(new WorkProgress("Drawing grain overlays",total>0?98+1.8*done/total:99.8,eta,done,total,false));
            });
            geometryToken=nextGeometry;
        }
        Editor.SetRuler(ruler.ValueKind==JsonValueKind.Array?ruler.EnumerateArray().Select(p=>p.EnumerateArray().Select(v=>v.GetDouble()).ToArray()).ToArray():null);
        var rawColumns=result.GetProperty("columns").EnumerateArray().Select(c=>c.GetString()!).ToList();
        var ordered=Preferred.SelectMany(prefix=>rawColumns.Where(c=>c==prefix||c.StartsWith(prefix+"_"))).Distinct().ToList();
        ordered.AddRange(rawColumns.Where(c=>!ordered.Contains(c)));
        if(!columns.SequenceEqual(ordered)){columns=ordered;BuildTable();}
        foreach(var row in rows)row.Cells=columns.Select(c=>row.Values.TryGetValue(c,out var v)&&v.HasValue?v.Value.ToString(c=="grain_id"?"0":"G6",CultureInfo.InvariantCulture):"—").ToArray();
        if(sortColumn is not null&&!columns.Contains(sortColumn))sortColumn=null;
        RefreshRows();SyncSelection();
        TableFootnote.Text=calibrated?$"Lengths in {currentUnit} · Area in {currentUnit}² · Centroids in image pixels · CSV retains full precision":"Sizes in pixels · Draw a ruler reference for mm or cm · CSV retains full precision";
        TableSubtitle.Text=$"{rows.Count:N0} grains · {selection.Count} selected · {(calibrated?"Calibrated measurements":"Pixel measurements")}";
        AppWindow.Title=$"{(dirty?"● ":"")}{Path.GetFileName(source)} — Segment Every Grain";
    }
    private string ColumnLabel(string col)
    {
        if(col=="grain_id")return "Grain";
        if(col.StartsWith("area"))return $"Area ({currentUnit}²)";
        if(col.StartsWith("major_axis_length"))return $"Major axis ({currentUnit})";
        if(col.StartsWith("minor_axis_length"))return $"Minor axis ({currentUnit})";
        if(col.StartsWith("perimeter"))return $"Perimeter ({currentUnit})";
        if(col=="centroid-0")return "Centroid Y (px)";
        if(col=="centroid-1")return "Centroid X (px)";
        if(col=="orientation")return "Orientation (rad)";
        return col.Replace('_',' ');
    }
    private int ColumnWidth(string col)=>col=="grain_id"?82:col.Contains("intensity")?150:140;
    private void BuildTable()
    {
        TableHeader.Children.Clear();TableHeader.ColumnDefinitions.Clear();
        var definitions=new System.Text.StringBuilder();var cells=new System.Text.StringBuilder();
        for(int i=0;i<columns.Count;i++) {
            string col=columns[i];int width=ColumnWidth(col);
            TableHeader.ColumnDefinitions.Add(new ColumnDefinition{Width=new GridLength(width)});
            var button=new Button{Content=ColumnLabel(col),Tag=col,FontSize=11,FontWeight=Microsoft.UI.Text.FontWeights.SemiBold,Padding=new Thickness(12,0,16,0),BorderThickness=new Thickness(0),Background=new SolidColorBrush(Colors.Transparent),HorizontalAlignment=HorizontalAlignment.Stretch,HorizontalContentAlignment=i==0?HorizontalAlignment.Left:HorizontalAlignment.Right,CornerRadius=new CornerRadius(0)};
            button.Click+=(_,_)=>{descending=sortColumn==col&&!descending;sortColumn=col;RefreshRows();};Grid.SetColumn(button,i);TableHeader.Children.Add(button);
            definitions.Append($"<ColumnDefinition Width='{width}'/>");
            cells.Append($"<TextBlock Grid.Column='{i}' Text='{{Binding Cells[{i}]}}' Margin='12,0,16,0' FontSize='12' VerticalAlignment='Center' TextAlignment='{(i==0?"Left":"Right")}' TextTrimming='CharacterEllipsis' Typography.NumeralAlignment='Tabular' />");
        }
        TableGrid.Width=columns.Sum(ColumnWidth);
        string xaml=$"<DataTemplate xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation'><Grid Height='34' BorderBrush='#EFF3ED' BorderThickness='0,0,0,1'><Grid.ColumnDefinitions>{definitions}</Grid.ColumnDefinitions>{cells}</Grid></DataTemplate>";
        Measurements.ItemTemplate=(DataTemplate)XamlReader.Load(xaml);
    }
    private void RefreshRows()
    {
        syncing=true;
        IEnumerable<MeasurementRow> visible=SelectedOnly.IsChecked==true?rows.Where(r=>selection.Contains(r.Id)):rows;
        if(sortColumn is string col)visible=descending?visible.OrderByDescending(r=>r.Values.GetValueOrDefault(col)??double.NegativeInfinity):visible.OrderBy(r=>r.Values.GetValueOrDefault(col)??double.PositiveInfinity);
        Measurements.ItemsSource=visible.ToList();
        foreach(var row in Measurements.Items.Cast<MeasurementRow>())if(selection.Contains(row.Id))Measurements.SelectedItems.Add(row);
        EmptyTable.Visibility=Measurements.Items.Count==0?Visibility.Visible:Visibility.Collapsed;
        EmptyTable.Text=SelectedOnly.IsChecked==true?"Select grains in the image to inspect them":"No grains to measure yet";
        foreach(Button header in TableHeader.Children.OfType<Button>())header.Content=ColumnLabel((string)header.Tag)+(sortColumn==(string)header.Tag?(descending?" ↓":" ↑"):"");
        syncing=false;
    }
    private void SyncSelection()
    {
        Editor.SetSelection(selection);
        if(SelectedOnly.IsChecked==true)RefreshRows();
        else {
            syncing=true;Measurements.SelectedItems.Clear();
            foreach(var row in Measurements.Items.Cast<MeasurementRow>())if(selection.Contains(row.Id))Measurements.SelectedItems.Add(row);
            syncing=false;
        }
        TableSubtitle.Text=$"{rows.Count:N0} grains · {selection.Count} selected · {(currentUnit=="px"?"Pixel measurements":"Calibrated measurements")}";
        UpdateControls();
    }
    private void Table_SelectionChanged(object sender,SelectionChangedEventArgs e)
    {
        if(syncing)return;
        selection.Clear();foreach(MeasurementRow row in Measurements.SelectedItems)selection.Add(row.Id);
        Editor.SetSelection(selection);TableSubtitle.Text=$"{rows.Count:N0} grains · {selection.Count} selected";UpdateControls();
    }
    private void Table_ItemClick(object sender,ItemClickEventArgs e){}
    private void SelectedOnly_Click(object sender,RoutedEventArgs e)=>RefreshRows();
    private void SetTool(string mode)
    {
        Editor.Mode=mode;
        foreach(var button in CanvasTools.Children.OfType<ToggleButton>())button.IsChecked=(string)button.Tag==mode;
        ToolHint.Text=mode switch {"pan"=>"Drag to pan · Ctrl + wheel to zoom","add"=>"Click inside a grain to create its mask","foreground"=>"Mark points inside the grain","background"=>"Mark points outside the grain","ruler"=>"Drag between two known ruler marks",_=>"Select grains · Ctrl + click for multiple"};
        if(mode is "foreground" or "background")PromptExpander.IsExpanded=true;
    }
    private void Tool_Click(object sender,RoutedEventArgs e){if(!busy)SetTool((string)((ToggleButton)sender).Tag);}
    private void Overlay_Toggled(object sender,RoutedEventArgs e){if(Editor is not null)Editor.SetOverlay(OverlaySwitch.IsOn);}
    private void Fill_Toggled(object sender,RoutedEventArgs e){if(Editor is not null)Editor.SetFill(FillSwitch.IsOn);}
    private void Fit_Click(object sender,RoutedEventArgs e)=>Editor.Fit();
    private void ClearPoints_Click(object sender,RoutedEventArgs e){Editor.ClearPrompts();SetTool("select");}
    private async Task<bool> ConfirmLeavingAsync()
    {
        if(!dirty)return true;
        var dialog=new ContentDialog{XamlRoot=Root.XamlRoot,Title="Keep your work?",Content="Save your grain corrections and calibration before opening another image or closing.",PrimaryButtonText="Save project",SecondaryButtonText="Discard changes",CloseButtonText="Keep editing",DefaultButton=ContentDialogButton.Primary};
        var result=await dialog.ShowAsync();
        if(result==ContentDialogResult.Primary)return await SaveAsync();
        return result==ContentDialogResult.Secondary;
    }
    private async void Open_Click(object sender,RoutedEventArgs e)
    {
        if(busy||!ready||!await ConfirmLeavingAsync())return;
        var picker=new FileOpenPicker();WinRT.Interop.InitializeWithWindow.Initialize(picker,hwnd);
        foreach(string ext in new[]{".jpg",".jpeg",".png",".tif",".tiff",".bmp"})picker.FileTypeFilter.Add(ext);
        var file=await picker.PickSingleFileAsync();if(file is null)return;
        selection.Clear();SelectedOnly.IsChecked=false;Editor.ClearPrompts();SetTool("select");
        await RunAsync("open",new {path=file.Path},"Opening image…","Image opened. Choose Segment image to find grain boundaries.");
    }
    private async void Project_Click(object sender,RoutedEventArgs e)
    {
        if(busy||!ready||!await ConfirmLeavingAsync())return;
        var picker=new FileOpenPicker();WinRT.Interop.InitializeWithWindow.Initialize(picker,hwnd);picker.FileTypeFilter.Add(".json");
        var file=await picker.PickSingleFileAsync();if(file is null)return;
        selection.Clear();SelectedOnly.IsChecked=false;Editor.ClearPrompts();SetTool("select");
        await RunAsync("open_project",new {path=file.Path},"Restoring your project…","Project restored. Measurements and calibration are ready.");
    }
    private async void Segment_Click(object sender,RoutedEventArgs e)
    {
        if(busy||!loaded)return;
        if(!double.IsFinite(MinimumArea.Value)||MinimumArea.Value<1||MinimumArea.Value!=Math.Floor(MinimumArea.Value)){ShowNotice("Check the minimum area","Enter a positive whole number of pixels.");return;}
        string variant=(string)((ComboBoxItem)ModelChoice.SelectedItem).Tag,device=(string)((ComboBoxItem)DeviceChoice.SelectedItem).Tag;
        Editor.ClearPrompts();SetTool("select");
        await RunAsync("segment",new {variant,backend=device,minimum=(int)MinimumArea.Value},"Preparing segmentation…","Segmentation complete. Select grains to inspect and refine their measurements.");
    }
    private async void Manual_Click(object sender,RoutedEventArgs e)=>await RunAsync("manual",new {variant=ChosenVariant,backend=ChosenBackend},"Preparing canvas…","Ready for manual masks. Use + to add a grain, or place foreground/background points.");
    private async void Delete_Click(object sender,RoutedEventArgs e)=>await RunAsync("delete",new {ids=selection.ToArray()},"Deleting selected grains…","Selected grains deleted. Ctrl+Z to undo.");
    private async void Merge_Click(object sender,RoutedEventArgs e)=>await RunAsync("merge",new {ids=selection.ToArray()},"Merging selected grains…","Grains merged. Measurements updated.");
    private async void Undo_Click(object sender,RoutedEventArgs e)=>await RunAsync("undo",null,"Undoing correction…","Correction undone.");
    private async void Redo_Click(object sender,RoutedEventArgs e)=>await RunAsync("redo",null,"Restoring correction…","Correction restored.");
    private async void Create_Click(object sender,RoutedEventArgs e)
    {
        var prompts=Editor.PromptData();
        if(await RunAsync("add",new {points=prompts.points,labels=prompts.labels,variant=ChosenVariant,backend=ChosenBackend},"Building a mask from your points…","New grain created. Measurements updated."))SetTool("select");
    }
    private void Ruler_Click(object sender,RoutedEventArgs e)
    {
        if(!double.IsFinite(ReferenceLength.Value)||ReferenceLength.Value<=0){ShowNotice("Check the ruler length","Enter the real length of the interval before drawing.");return;}
        SetTool("ruler");
    }
    private async Task CalibrateAsync(double[][]? points)
    {
        if(!double.IsFinite(ReferenceLength.Value)||ReferenceLength.Value<=0){ShowNotice("Check the ruler length","Enter a positive real-world length in mm or cm.");return;}
        string unit=UnitChoice.SelectedIndex==1?"cm":"mm";
        await RunAsync("calibrate",new {points,length=ReferenceLength.Value,unit},"Updating calibrated measurements…","Ruler calibrated. The table and CSV now use real-world units.");
    }
    private async void ApplyCalibration_Click(object sender,RoutedEventArgs e)=>await CalibrateAsync(Editor.Ruler);
    private async void ClearCalibration_Click(object sender,RoutedEventArgs e)=>await RunAsync("clear_calibration",null,"Removing calibration…","Calibration removed. Measurements are in pixels.");
    private async Task<bool> SaveAsync(bool saveAs=false)
    {
        if(busy||!loaded)return false;
        if(!saveAs && savedFolder is not null && Directory.Exists(savedFolder))
            return await RunAsync("save",new {path=savedFolder},"Saving your corrections…",$"Project saved to {savedFolder}");
        var picker=new FolderPicker();WinRT.Interop.InitializeWithWindow.Initialize(picker,hwnd);picker.FileTypeFilter.Add("*");
        var folder=await picker.PickSingleFolderAsync();if(folder is null)return false;
        if(File.Exists(Path.Combine(folder.Path,"project.json"))) {
            var confirm=new ContentDialog{XamlRoot=Root.XamlRoot,Title="Replace this saved project?",Content="This folder already contains a grain project. Its image, masks and measurements will be replaced.",PrimaryButtonText="Replace project",CloseButtonText="Choose another folder",DefaultButton=ContentDialogButton.Close};
            if(await confirm.ShowAsync()!=ContentDialogResult.Primary)return false;
        }
        return await RunAsync("save",new {path=folder.Path},"Saving image, masks and measurements…",$"Project saved to {folder.Path}");
    }
    private async void Save_Click(object sender,RoutedEventArgs e)=>await SaveAsync();
    private async void SaveAs_Click(object sender,RoutedEventArgs e)=>await SaveAsync(true);
    private async void Export_Click(object sender,RoutedEventArgs e)
    {
        if(busy||!loaded)return;
        var picker=new FileSavePicker{SuggestedFileName="measurements"};WinRT.Interop.InitializeWithWindow.Initialize(picker,hwnd);
        picker.FileTypeChoices.Add("CSV measurements",new List<string>{".csv"});
        var file=await picker.PickSaveFileAsync();if(file is null)return;
        await RunAsync("export",new {path=file.Path},"Exporting grain measurements…",$"CSV exported to {file.Path}");
    }
    private async void Setup_Click(object sender,RoutedEventArgs e)
    {
        if(busy){ShowNotice("Still processing","Finish the current operation before opening setup.",InfoBarSeverity.Informational);return;}
        if(!await ConfirmLeavingAsync())return;
        string setup=Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"..","Machine Setup.exe"));
        if(!File.Exists(setup))setup=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SegmentEveryGrainDesktop","Segment Every Grain.exe");
        try{
            var start=new ProcessStartInfo(setup,"--setup"){UseShellExecute=false,CreateNoWindow=true};
            start.Environment["SEGMENTEVERYGRAIN_NATIVE_APP"]=Path.Combine(AppContext.BaseDirectory,"SegmentEveryGrain.exe");
            Process.Start(start);
            allowClose=true;Close();
        }
        catch(Exception ex){ShowNotice("Couldn't open setup",ex.Message);}
    }
    private void ResultsFolder_Click(object sender,RoutedEventArgs e)
    {
        if(savedFolder is null||!Directory.Exists(savedFolder)){ShowNotice("No saved results folder","Save your project first, then open its results here.",InfoBarSeverity.Informational);return;}
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(savedFolder){UseShellExecute=true});
    }
    private async void About_Click(object sender,RoutedEventArgs e)
    {
        await new ContentDialog{XamlRoot=Root.XamlRoot,Title="Segment Every Grain",Content="A native WinUI 3 workspace for grain segmentation and measurement.\n\nPython, U-Net and SAM 2.1 run locally in a separate processing engine. GPU acceleration uses DirectML.\n\nCtrl+O · Open image\nCtrl+Shift+O · Open project\nCtrl+S · Save project\nCtrl+Z / Ctrl+Y · Undo / redo\nV · Select   H · Pan   A · Add   F · Fit\nEscape · Clear selection and points\n\nUpstream license notices are included alongside the application.",CloseButtonText="Back to workspace"}.ShowAsync();
    }
    private void Root_KeyDown(object sender,KeyRoutedEventArgs e)
    {
        if(busy)return;
        bool ctrl=InputKeyboardSource.GetKeyStateForCurrentThread(VirtualKey.Control).HasFlag(CoreVirtualKeyStates.Down);
        // Let text and numeric editors own their editing keys.
        if(e.OriginalSource is TextBox or NumberBox or PasswordBox)return;
        if(ctrl) {
            switch(e.Key){case VirtualKey.Z:Undo_Click(this,new RoutedEventArgs());break;case VirtualKey.Y:Redo_Click(this,new RoutedEventArgs());break;default:return;}
        }else {
            switch(e.Key){case VirtualKey.Delete:if(selection.Count>0)Delete_Click(this,new RoutedEventArgs());break;case VirtualKey.F:Editor.Fit();break;case VirtualKey.V:SetTool("select");break;case VirtualKey.H:SetTool("pan");break;case VirtualKey.A:SetTool("add");break;case VirtualKey.Escape:selection.Clear();Editor.ClearPrompts();SetTool("select");SyncSelection();break;default:return;}
        }
        e.Handled=true;
    }
    private void Divider_Pressed(object sender,PointerRoutedEventArgs e)
    {
        if(!e.GetCurrentPoint((UIElement)sender).Properties.IsLeftButtonPressed)return;
        dividerDragging=true;dividerY=e.GetCurrentPoint(WorkspaceGrid).Position.Y;tableHeight=WorkspaceGrid.RowDefinitions[2].ActualHeight;((UIElement)sender).CapturePointer(e.Pointer);
    }
    private void Divider_Moved(object sender,PointerRoutedEventArgs e)
    {
        if(!dividerDragging)return;
        double y=e.GetCurrentPoint(WorkspaceGrid).Position.Y;
        WorkspaceGrid.RowDefinitions[2].Height=new GridLength(Math.Clamp(tableHeight+dividerY-y,150,Math.Max(150,WorkspaceGrid.ActualHeight-230)));
    }
    private void Divider_Released(object sender,PointerRoutedEventArgs e){dividerDragging=false;((UIElement)sender).ReleasePointerCapture(e.Pointer);}

    private async Task VerifyAsync(string output)
    {
        Directory.CreateDirectory(output);string report=Path.Combine(output,"winui-ui.json");
        var checks=new Dictionary<string,object>();
        var updates=new List<WorkProgress>();
        void Observe(WorkProgress update)=>updates.Add(update);
        backend.Progress+=Observe;
        try {
            if(!loaded||rows.Count<2)throw new InvalidOperationException("Open a populated project before UI verification.");
            busy=false;UpdateControls();
            int original=rows.Count;checks["loaded_grains"]=original;
            FillSwitch.IsOn=true;
            if(!Editor.FillVisible||Editor.DistinctFillColors<Math.Min(rows.Count,50))throw new Exception("Individual grain colors did not render.");
            OverlaySwitch.IsOn=false;
            if(Editor.OutlinesVisible||!Editor.FillVisible)throw new Exception("Fill and outlines are not independent.");
            FillSwitch.IsOn=false;
            if(Editor.FillVisible||Editor.OutlinesVisible)throw new Exception("Original-image mode failed.");
            OverlaySwitch.IsOn=true;FillSwitch.IsOn=true;
            checks["independent_outlines_and_distinct_color_fills"]=true;
            selection.Add(rows[0].Id);SyncSelection();
            if(Measurements.SelectedItems.Count!=1||!DeleteButton.IsEnabled)throw new InvalidOperationException("Linked selection did not update.");
            checks["linked_selection"]=true;
            if(!await RunAsync("delete",new {ids=selection.ToArray()},"Verifying correction…","Verification: deletion"))throw new Exception(Notice.Message);
            if(rows.Count!=original-1)throw new Exception("Delete did not update the native table.");
            if(!await RunAsync("undo",null,"Verifying undo…","Verification: undo")||rows.Count!=original)throw new Exception("Undo failed.");
            if(!await RunAsync("redo",null,"Verifying redo…","Verification: redo")||rows.Count!=original-1)throw new Exception("Redo failed.");
            await RunAsync("undo",null,"Restoring grains…","Verification: restored");
            checks["delete_undo_redo"]=true;
            sortColumn=columns.First(c=>c.StartsWith("area"));descending=true;RefreshRows();
            var visible=Measurements.Items.Cast<MeasurementRow>().ToList();
            if(visible[0].Values[sortColumn]<visible[^1].Values[sortColumn])throw new Exception("Table sort failed.");
            checks["numeric_sort"]=true;
            selection.Clear();selection.Add(rows[0].Id);SelectedOnly.IsChecked=true;SyncSelection();
            if(Measurements.Items.Count!=1)throw new Exception("Selected-only filtering failed.");
            SelectedOnly.IsChecked=false;selection.Clear();SyncSelection();RefreshRows();checks["selected_filter"]=true;
            var reference=new[]{new[]{20.0,20.0},new[]{120.0,20.0}};
            if(!await RunAsync("calibrate",new {points=reference,length=10,unit="mm"},"Verifying calibration…","Verification: calibrated"))throw new Exception(Notice.Message);
            if(!columns.Contains("area_mm2"))throw new Exception("Calibrated table headers did not update.");
            checks["native_calibration"]=true;
            string csv=Path.Combine(output,"native-table.csv");
            if(!await RunAsync("export",new {path=csv},"Verifying CSV…","Verification: CSV"))throw new Exception(Notice.Message);
            var lines=await File.ReadAllLinesAsync(csv);var headers=lines[0].Split(',');
            if(lines.Length!=rows.Count+1)throw new Exception("CSV row count mismatch.");
            for(int r=0;r<rows.Count;r++) {
                var values=lines[r+1].Split(',');
                for(int c=0;c<headers.Length;c++) {
                    double expected=rows[r].Values[headers[c]]??double.NaN;
                    if(double.IsNaN(expected)&&string.IsNullOrEmpty(values[c]))continue;
                    double actual=double.Parse(values[c],CultureInfo.InvariantCulture);
                    if(Math.Abs(actual-expected)>Math.Max(1,Math.Abs(expected))*1e-9)throw new Exception("CSV value mismatch.");
                }
            }
            checks["csv_matches_live_table"]=true;
            await RunAsync("undo",null,"Restoring original calibration…","Verification: restored");
            string project=Path.Combine(output,"native-ui-project");
            await RunAsync("save",new {path=project},"Verifying save…","Verification: saved");
            if(dirty)throw new Exception("Saved project still marked dirty.");
            await RunAsync("open_project",new {path=Path.Combine(project,"project.json")},"Verifying reopen…","Verification: reopened");
            if(rows.Count!=original||dirty)throw new Exception("Project restore mismatch.");checks["save_reopen"]=true;
            foreach(var size in new[]{new SizeInt32(1120,760),new SizeInt32(1460,960)}) {
                AppWindow.Resize(size);await Task.Delay(300);
                if(Editor.ActualHeight<80||Measurements.ActualHeight<50||Measurements.ActualWidth<200)throw new Exception("A pane became unusable after resize.");
            }
            checks["window_sizes"]=true;
            if(!updates.Any(p=>p.Percent.HasValue)||!updates.Any(p=>p.Total>0&&!p.Indeterminate))throw new Exception("Structured work progress was not received.");
            if(operationClock.IsRunning||OperationBar.Visibility!=Visibility.Collapsed)throw new Exception("Progress did not clear after processing.");
            if(!Editor.FillVisible||Editor.DistinctFillColors<Math.Min(rows.Count,50))throw new Exception("Grain fill colors were lost after editing or reopening.");
            checks["bottom_progress_for_processing"]=true;
            checks["progress_events_received"]=updates.Count;
            Editor.Fit();checks["passed"]=true;
            await File.WriteAllTextAsync(report,JsonSerializer.Serialize(checks,new JsonSerializerOptions{WriteIndented=true}));
            StatusLabel.Text="Verification passed · Linked selection, corrections, calibration, CSV and project restore.";
        }catch(Exception ex){checks["passed"]=false;checks["error"]=ex.ToString();await File.WriteAllTextAsync(report,JsonSerializer.Serialize(checks,new JsonSerializerOptions{WriteIndented=true}));throw;}
        finally{backend.Progress-=Observe;}
    }
}

[Microsoft.UI.Xaml.Data.Bindable]
public sealed class MeasurementRow
{
    public int Id {get;}
    public Dictionary<string,double?> Values {get;}=new();
    public string[] Cells {get;set;}=Array.Empty<string>();
    public MeasurementRow(JsonElement grain)
    {
        Id=grain.GetProperty("id").GetInt32();
        foreach(var value in grain.GetProperty("values").EnumerateObject())Values[value.Name]=value.Value.ValueKind==JsonValueKind.Number?value.Value.GetDouble():null;
    }
}
