"""
Generate a Slurm array job script to run all .sh files in the slurm/ folder as an array job.
"""

from pathlib import Path

job_name="pipeline"
slurm_dir=Path("~/pipeline/slurm").expanduser() # Directory containing the .sh job files
output_file="run_all_jobs.sh"  # Name of the output batch script, placed in current dir
time_limit="01:00:00"          # Time limit per job (format: HH:MM:SS)
memory="8G"                    # Memory per job (e.g., "4G", "2000M")
cpus_per_task=1                # Number of CPUs per task

# Get all .sh files in the directory
slurm_path = Path(slurm_dir)
if not slurm_path.exists():
    raise FileNotFoundError(f"Directory '{slurm_dir}' does not exist!")

sh_files = sorted(slurm_path.glob("*.sh"))

if not sh_files:
    raise ValueError(f"No .sh files found in '{slurm_dir}'!")

num_jobs = len(sh_files)
print(f"Found {num_jobs} .sh files in '{slurm_dir}/'")

# Generate the batch script
batch_script = f"""#!/bin/bash
# vim: ft=slurm
# Auto-generated Slurm batch script
# Generated for {num_jobs} jobs from {slurm_dir}/

#SBATCH --job-name={job_name}
#SBATCH --array=0-{num_jobs - 1}
#SBATCH --time={time_limit}
#SBATCH --mem={memory}
#SBATCH --cpus-per-task={cpus_per_task}
#SBATCH --output=logs/{job_name}_%A_%a.out
#SBATCH --error=logs/{job_name}_%A_%a.err

# Create logs directory if it doesn't exist
mkdir -p logs

# Array of job scripts
jobs=(
"""
# Add all job paths to the array
for sh_file in sh_files:
    batch_script += f'    "{sh_file}"\n'

batch_script += """)

# Get the job script for this array task
job_script="${jobs[$SLURM_ARRAY_TASK_ID]}"

echo "=================================================="
echo "Running job $SLURM_ARRAY_TASK_ID: $job_script"
echo "Started at: $(date)"
echo "Running on node: $(hostname)"
echo "=================================================="

# Execute the job script
bash "$job_script"

exit_code=$?

echo "=================================================="
echo "Finished at: $(date)"
echo "Exit code: $exit_code"
echo "=================================================="

exit $exit_code
"""

# Write the batch script
with open(output_file, 'w') as f:
    f.write(batch_script)

# Make it executable
# os.chmod(output_file, 0o755)

print(f"\nGenerated batch script: {output_file}")
print(f"Array size: 0-{num_jobs - 1} ({num_jobs} jobs)")
print(f"\nTo submit the job, run:")
print(f"  sbatch {output_file}")
print(f"\nJob files included:")
for i, sh_file in enumerate(sh_files):
    print(f"  [{i}] {sh_file}")

