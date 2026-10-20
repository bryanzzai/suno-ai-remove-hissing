using System.Collections.ObjectModel;
using System.Windows;
using Microsoft.Win32;
using SunoAiRemoveHissing.Models;
using SunoAiRemoveHissing.Services;

namespace SunoAiRemoveHissing;

public partial class MainWindow : Window
{
    private readonly AudioLibraryScanner _scanner = new();
    private readonly CleaningEngine _engine = new();
    private CancellationTokenSource? _cts;

    public ObservableCollection<AudioItem> Tracks { get; } = [];

    public MainWindow()
    {
        InitializeComponent();
        DataContext = this;
    }

    private void BrowseInput_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectFolder("Choose a folder containing Suno audio files", InputPathTextBox.Text);
        if (selected is null) return;
        InputPathTextBox.Text = selected;
        if (string.IsNullOrWhiteSpace(OutputPathTextBox.Text))
            OutputPathTextBox.Text = Path.Combine(selected, "CLEANED");
    }

    private void BrowseOutput_Click(object sender, RoutedEventArgs e)
    {
        var selected = SelectFolder("Choose the folder for cleaned files", OutputPathTextBox.Text);
        if (selected is not null) OutputPathTextBox.Text = selected;
    }

    private void BrowsePython_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "Choose python.exe", Filter = "Python executable|python.exe|All files|*.*" };
        if (dialog.ShowDialog(this) == true) PythonPathTextBox.Text = dialog.FileName;
    }

    private string? SelectFolder(string title, string current)
    {
        var dialog = new OpenFolderDialog { Title = title, Multiselect = false };
        if (Directory.Exists(current)) dialog.InitialDirectory = current;
        return dialog.ShowDialog(this) == true ? dialog.FolderName : null;
    }

    private async void ScanButton_Click(object sender, RoutedEventArgs e)
    {
        if (!ValidateFolders()) return;
        BeginOperation();
        try
        {
            StatusTextBlock.Text = "Scanning audio files…";
            var input = InputPathTextBox.Text.Trim();
            var output = OutputPathTextBox.Text.Trim();
            var found = await Task.Run(() => _scanner.Scan(input, output, _cts!.Token), _cts!.Token);
            Tracks.Clear();
            foreach (var item in found) Tracks.Add(item);
            CountTextBlock.Text = $"{Tracks.Count} files";
            ProgressBar.Maximum = Math.Max(1, Tracks.Count);
            ProgressBar.Value = Tracks.Count;
            StatusTextBlock.Text = Tracks.Count == 0 ? "No supported audio files found." : $"Scan complete. {Tracks.Count} files ready.";
        }
        catch (OperationCanceledException) { StatusTextBlock.Text = "Scan cancelled."; }
        catch (Exception ex) { ShowError("Scan failed", ex); }
        finally { EndOperation(); }
    }

    private async void RunButton_Click(object sender, RoutedEventArgs e)
    {
        if (Tracks.Count == 0) { ShowInfo("Scan a folder before starting cleanup."); return; }
        if (!ValidateFolders()) return;
        if (DynamicFullMixTestCheckBox.IsChecked != true && HarmonicDeFizzerCheckBox.IsChecked != true)
        {
            ShowInfo("Choose at least one whole-mix effect.");
            return;
        }
        var selected = Tracks.Where(track => track.IsSelected).ToArray();
        if (selected.Length == 0) { ShowInfo("Tick at least one audio file to process."); return; }
        var script = Path.Combine(AppContext.BaseDirectory, "backend", "SunoClean_AI.py");
        BeginOperation();
        ProgressBar.Minimum = 0;
        ProgressBar.Maximum = selected.Length;
        ProgressBar.Value = 0;
        foreach (var track in Tracks) track.Status = track.IsSelected ? "Queued" : "Not selected";

        try
        {
            var progress = new Progress<string>(HandleEngineLine);
            await _engine.RunAsync(PythonPathTextBox.Text.Trim(), script, InputPathTextBox.Text.Trim(), OutputPathTextBox.Text.Trim(),
                selected.Select(track => track.RelativePath), DynamicFullMixTestCheckBox.IsChecked == true,
                HarmonicDeFizzerCheckBox.IsChecked == true, OverwriteCheckBox.IsChecked == true, progress, _cts!.Token);
            StatusTextBlock.Text = "Cleanup complete.";
        }
        catch (OperationCanceledException) { StatusTextBlock.Text = "Cleanup cancelled."; }
        catch (Exception ex) { ShowError("Cleanup failed", ex); }
        finally { EndOperation(); }
    }

    private void HandleEngineLine(string line)
    {
        // Machine-readable backend protocol: PROGRESS|phase|completed|total|relative-path|message
        if (!line.StartsWith("PROGRESS|", StringComparison.Ordinal)) return;
        var parts = line.Split('|', 6);
        if (parts.Length != 6 || !int.TryParse(parts[2], out var completed) || !int.TryParse(parts[3], out var total)) return;
        var track = Tracks.FirstOrDefault(x => string.Equals(x.RelativePath, parts[4], StringComparison.OrdinalIgnoreCase));
        if (track is not null) track.Status = parts[5];
        ProgressBar.Maximum = Math.Max(1, total);
        ProgressBar.Value = Math.Clamp(completed, 0, total);
        StatusTextBlock.Text = parts[5];
    }

    private bool ValidateFolders()
    {
        if (!Directory.Exists(InputPathTextBox.Text.Trim())) { ShowInfo("Choose a valid input folder."); return false; }
        if (string.IsNullOrWhiteSpace(OutputPathTextBox.Text)) { ShowInfo("Choose an output folder."); return false; }
        return true;
    }

    private void BeginOperation()
    {
        _cts = new CancellationTokenSource();
        ScanButton.IsEnabled = false; RunButton.IsEnabled = false; CancelButton.IsEnabled = true;
    }

    private void EndOperation()
    {
        ScanButton.IsEnabled = true; RunButton.IsEnabled = true; CancelButton.IsEnabled = false;
        _cts?.Dispose(); _cts = null;
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e) => _cts?.Cancel();
    private void ShowInfo(string message) => MessageBox.Show(this, message, "Suno AI Remove Hissing", MessageBoxButton.OK, MessageBoxImage.Information);
    private void ShowError(string title, Exception ex) => MessageBox.Show(this, ex.Message, title, MessageBoxButton.OK, MessageBoxImage.Error);
}
