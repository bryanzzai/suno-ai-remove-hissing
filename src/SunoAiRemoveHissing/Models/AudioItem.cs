using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace SunoAiRemoveHissing.Models;

public sealed class AudioItem : INotifyPropertyChanged
{
    private string _status = "Ready";
    private bool _isSelected = true;

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

    public bool IsSelected
    {
        get => _isSelected;
        set
        {
            if (_isSelected == value) return;
            _isSelected = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(IsSelected)));
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
}
