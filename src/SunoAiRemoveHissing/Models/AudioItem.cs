using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace SunoAiRemoveHissing.Models;

public sealed class AudioItem : INotifyPropertyChanged
{
    private string _status = "Ready";

    public required string FullPath { get; init; }
    public required string RelativePath { get; init; }
    public required string Folder { get; init; }
    public required string FileName { get; init; }

    public string Status
    {
        get => _status;
        set
        {
            if (_status == value) return;
            _status = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Status)));
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
}
