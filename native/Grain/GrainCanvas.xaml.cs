using System.Text.Json;
using Microsoft.UI.Input;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;
using Windows.System;
using Windows.UI;
using Windows.UI.Core;
using Outline=Microsoft.UI.Xaml.Shapes.Path;

namespace Grain;
public sealed partial class GrainCanvas : UserControl
{
    private readonly Dictionary<int,Outline> shapes=new();
    private readonly List<(Point point,bool foreground)> prompts=new();
    private HashSet<int> selected=new();
    private string? imagePath;
    private bool overlay=true,fill,dragging;
    private Point anchor,panAnchor;
    private double panX,panY;
    private double drawingScale=1;
    public string Mode {get;set;}="select";
    public double[][]? Ruler {get;private set;}
    public event Action<int?,bool>? GrainPicked;
    public event Action<double,double,bool>? PointPlaced;
    public event Action<double[][]>? RulerDrawn;
    public event Action<double>? ZoomChanged;
    public GrainCanvas(){InitializeComponent();}
    private static SolidColorBrush Brush(byte a,byte r,byte g,byte b)=>new(Color.FromArgb(a,r,g,b));
    public async Task LoadImageAsync(string path,int width,int height)
    {
        if(imagePath==path)return;
        imagePath=path;drawingScale=Math.Min(1,2000.0/Math.Max(width,height));
        Surface.Width=Photo.Width=width*drawingScale;Surface.Height=Photo.Height=height*drawingScale;
        Outlines.Width=Marks.Width=width;Outlines.Height=Marks.Height=height;
        Outlines.RenderTransform=new ScaleTransform{ScaleX=drawingScale,ScaleY=drawingScale};
        Marks.RenderTransform=new ScaleTransform{ScaleX=drawingScale,ScaleY=drawingScale};
        prompts.Clear();Ruler=null;Marks.Children.Clear();
        var bitmap=new BitmapImage();
        var file=await Windows.Storage.StorageFile.GetFileFromPathAsync(path);
        using var stream=await file.OpenReadAsync();await bitmap.SetSourceAsync(stream);Photo.Source=bitmap;
        DispatcherQueue.TryEnqueue(Fit);
    }
    public void Fit()
    {
        if(Surface.Width<2||Viewport.ActualWidth<1)return;
        float zoom=(float)Math.Clamp(Math.Min((Viewport.ActualWidth-26)/Surface.Width,(Viewport.ActualHeight-26)/Surface.Height),.1,8);
        Viewport.ChangeView(0,0,zoom,disableAnimation:true);
    }
    public async Task SetGeometryAsync(JsonElement grains,Action<int,int>? progress=null)
    {
        shapes.Clear();Outlines.Children.Clear();
        int completed=0,total=grains.GetArrayLength();progress?.Invoke(0,total);
        foreach(var grain in grains.EnumerateArray()) {
            int id=grain.GetProperty("id").GetInt32();
            var geometry=new PathGeometry{FillRule=FillRule.EvenOdd};
            foreach(var ring in grain.GetProperty("rings").EnumerateArray()) {
                var points=ring.EnumerateArray().Select(p=>new Point(p[0].GetDouble(),p[1].GetDouble())).ToList();
                if(points.Count<3)continue;
                var figure=new PathFigure{StartPoint=points[0],IsClosed=true,IsFilled=true};
                var segment=new PolyLineSegment();foreach(var point in points.Skip(1))segment.Points.Add(point);
                figure.Segments.Add(segment);geometry.Figures.Add(figure);
            }
            var shape=new Outline{Data=geometry,Tag=id,StrokeLineJoin=PenLineJoin.Round};
            ToolTipService.SetToolTip(shape,$"Grain {id}");shapes[id]=shape;Outlines.Children.Add(shape);
            completed++;
            if(completed%32==0){progress?.Invoke(completed,total);await Task.Delay(1);}
        }
        Restyle();
        progress?.Invoke(total,total);
    }
    public void SetSelection(IEnumerable<int> ids)
    {
        selected=new HashSet<int>(ids);Restyle();
    }
    public void SetOverlay(bool visible){overlay=visible;Restyle();}
    public void SetFill(bool visible){fill=visible;Restyle();}
    // Golden-angle hues give each stable grain ID a different reproducible color.
    // Fill is independent of outlines and survives selection, zoom and rebuilding.
    private static SolidColorBrush GrainFill(int id)
    {
        double hue=((id*137.50776405003785)%360+360)%360;
        double saturation=.68,value=.94,c=value*saturation,x=c*(1-Math.Abs((hue/60)%2-1)),m=value-c;
        (double r,double g,double b)=hue switch {
            <60=>(c,x,0.0),<120=>(x,c,0.0),<180=>(0.0,c,x),<240=>(0.0,x,c),<300=>(x,0.0,c),_=>(c,0.0,x)};
        return Brush(165,(byte)Math.Round((r+m)*255),(byte)Math.Round((g+m)*255),(byte)Math.Round((b+m)*255));
    }
    internal int DistinctFillColors=>shapes.Values.Select(p=>(p.Fill as SolidColorBrush)?.Color).Distinct().Count();
    internal bool OutlinesVisible=>overlay;
    internal bool FillVisible=>fill;
    private void Restyle()
    {
        double z=Math.Max(.001,Viewport.ZoomFactor*drawingScale);
        foreach(var (id,path) in shapes) {
            bool active=selected.Contains(id);
            path.Stroke=overlay||active?(active?Brush(255,255,199,85):Brush(230,32,82,57)):Brush(0,0,0,0);
            path.Fill=fill?GrainFill(id):active?Brush(100,255,195,67):Brush(0,0,0,0);
            path.StrokeThickness=(active?2.4:1.2)/z;
        }
        DrawMarks();
    }
    public (double[][] points,int[] labels) PromptData()=>
        (prompts.Select(p=>new[]{p.point.X,p.point.Y}).ToArray(),prompts.Select(p=>p.foreground?1:0).ToArray());
    public void ClearPrompts(){prompts.Clear();DrawMarks();}
    public void SetRuler(double[][]? ruler){Ruler=ruler;DrawMarks();}
    private void DrawMarks()
    {
        Marks.Children.Clear();double z=Math.Max(.001,Viewport.ZoomFactor*drawingScale);
        if(Ruler is {Length:2}) {
            var line=new Line{X1=Ruler[0][0],Y1=Ruler[0][1],X2=Ruler[1][0],Y2=Ruler[1][1],Stroke=Brush(255,255,184,72),StrokeThickness=2.5/z};Marks.Children.Add(line);
            foreach(var p in Ruler){var dot=new Ellipse{Width=8/z,Height=8/z,Fill=Brush(255,255,184,72),Stroke=Brush(255,255,255,255),StrokeThickness=1/z};Canvas.SetLeft(dot,p[0]-4/z);Canvas.SetTop(dot,p[1]-4/z);Marks.Children.Add(dot);}
        }
        foreach(var (p,fg) in prompts) {
            var dot=new Ellipse{Width=12/z,Height=12/z,Fill=fg?Brush(255,38,177,115):Brush(255,228,84,73),Stroke=Brush(255,255,255,255),StrokeThickness=2/z};
            Canvas.SetLeft(dot,p.X-6/z);Canvas.SetTop(dot,p.Y-6/z);Marks.Children.Add(dot);
        }
    }
    private void View_Changed(object sender,ScrollViewerViewChangedEventArgs e)
    {
        ZoomChanged?.Invoke(Viewport.ZoomFactor*drawingScale);if(!e.IsIntermediate)Restyle();
    }
    private Point ImagePoint(PointerRoutedEventArgs e)
    {
        var p=e.GetCurrentPoint(Surface).Position;return new Point(Math.Clamp(p.X/drawingScale,0,Surface.Width/drawingScale-1),Math.Clamp(p.Y/drawingScale,0,Surface.Height/drawingScale-1));
    }
    private void Surface_Pressed(object sender,PointerRoutedEventArgs e)
    {
        var current=e.GetCurrentPoint(Surface);if(!current.Properties.IsLeftButtonPressed||!IsEnabled)return;
        var p=ImagePoint(e);
        if(Mode is "pan" or "ruler") {
            dragging=true;anchor=p;panAnchor=e.GetCurrentPoint(Host).Position;panX=Viewport.HorizontalOffset;panY=Viewport.VerticalOffset;
            Surface.CapturePointer(e.Pointer);if(Mode=="ruler"){Ruler=new[]{new[]{p.X,p.Y},new[]{p.X,p.Y}};DrawMarks();}
        } else if(Mode=="select") {
            bool ctrl=InputKeyboardSource.GetKeyStateForCurrentThread(VirtualKey.Control).HasFlag(CoreVirtualKeyStates.Down);
            GrainPicked?.Invoke(e.OriginalSource is Outline shape&&shape.Tag is int id?id:null,ctrl);
        } else {
            bool fg=Mode!="background";
            if(Mode!="add"){prompts.Add((p,fg));DrawMarks();}
            PointPlaced?.Invoke(p.X,p.Y,fg);
        }
        e.Handled=true;
    }
    private void Surface_Moved(object sender,PointerRoutedEventArgs e)
    {
        if(!dragging)return;
        if(Mode=="ruler") {var p=ImagePoint(e);Ruler=new[]{new[]{anchor.X,anchor.Y},new[]{p.X,p.Y}};DrawMarks();}
        else if(Mode=="pan") {var p=e.GetCurrentPoint(Host).Position;Viewport.ChangeView(panX-(p.X-panAnchor.X),panY-(p.Y-panAnchor.Y),null,true);}
        e.Handled=true;
    }
    private void Surface_Released(object sender,PointerRoutedEventArgs e)
    {
        if(!dragging)return;dragging=false;Surface.ReleasePointerCapture(e.Pointer);
        if(Mode=="ruler" && Ruler is not null)RulerDrawn?.Invoke(Ruler);
        e.Handled=true;
    }
    private void Surface_Canceled(object sender,PointerRoutedEventArgs e){dragging=false;Surface.ReleasePointerCapture(e.Pointer);}
}
