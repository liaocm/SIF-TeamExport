#!/usr/bin/env python3

import os, argparse, sys, io
import PIL
import time
from PIL import Image
from math import sqrt
from data import data_dict
cards = data_dict()
total_cards = len(cards) - 10 # 9 SR match cards (#10001, ..., #10009) + #0

#-------- CONFIG --------#
OUTPUT_MODE = True
SCALED_OUTPUT_PATH_PREFIX = 'output/scaled-'
JSON_OUTPUT_PATH_PREFIX = 'output/'
PEAK_THRESHOLD_RATIO = 0.96
PEAK_COMPRESSION_LENGTH = 80
IMAGE_SPACE_SCALER = 134
IMAGE_CONVERSION_SCALER = 1128 / 846
#------ END CONFIG ------#

def vertical_line_sum(img, pixels, ratio=4, scan_ratio = 0.0):
    result = [0 for _ in range(int(img.size[0] * scan_ratio))]
    for i in range(int(img.size[0] * scan_ratio), img.size[0]):
        curr = 0
        for j in range(img.size[1]//ratio, img.size[1]*(ratio-1)//ratio):
            curr += (pixels[i, j][0] + pixels[i, j][1] + pixels[i, j][2])//3 
        result.append(curr)
    return result

def horizontal_line_sum(img, pixels, ratio=4):
    result = []
    for j in range(img.size[1]):
        curr = 0
        for i in range(img.size[0]//ratio, img.size[0]*(ratio-1)//ratio):
            curr += (pixels[i, j][0] + pixels[i, j][1] + pixels[i, j][2])//3
        result.append(curr)
    return result

def find_peaks(sum_vec, threshold_ratio = PEAK_THRESHOLD_RATIO):
    peaks = []
    last = -999999
    threshold = max(sum_vec) * threshold_ratio
    for i in range(len(sum_vec)):
        curr = sum_vec[i]
        if curr < last:
            if last > threshold:
                peaks.append([i-1, last])
        last = curr
    return peaks

def compress_peaks(peaks_vec):
    res = []
    last = peaks_vec[0]
    threshold = PEAK_COMPRESSION_LENGTH
    i_s = []
    for i in range(len(peaks_vec)):
        if peaks_vec[i][0] - last[0] > threshold:
            res.append(last)
            i_s.append(i)
        last = peaks_vec[i]
    return res  

def calculate_scale(compressed, num_items = 4):
    avg = 0
    for i in range(num_items):
        avg += compressed[i+1][0] - compressed[i][0]
    return IMAGE_SPACE_SCALER / avg * 4

# First, rescale image.
def rescale_image(img, pixels, output_mode = False, _scan_ratio = 0.1, output_path = 'output/default.png'):
    scale = calculate_scale(
        compress_peaks(
            find_peaks(
                vertical_line_sum(img, pixels, scan_ratio=_scan_ratio))))
    scaled_img = img.resize((int(img.size[0]*scale),int(img.size[1]*scale)), 
                            PIL.Image.ANTIALIAS)
    # crop the image if it is too long
    if scaled_img.size[0] / scaled_img.size[1] >= 1.5:
        new_width = int(IMAGE_CONVERSION_SCALER * scaled_img.size[1])
        scaled_img = scaled_img.crop(((scaled_img.size[0]-new_width)//4, 
                                     0, 
                                     scaled_img.size[0]-(scaled_img.size[0]-new_width)//4, 
                                     scaled_img.size[1]))
    if output_mode:
        scaled_img.save(output_path)
    return scaled_img

def get_targets(img, pixels):
  # Precondition: the image is scaled.
  # Figure out the start and end point of each team member.
  # This will be a 8 x 4 grid

  horizontal_breaks = compress_peaks(find_peaks(vertical_line_sum(img, pixels)))
  vertical_breaks = compress_peaks(find_peaks(horizontal_line_sum(img, pixels)))

  # Calculate average
  havg = 0
  vavg = 0
  for i in range(4):
      havg += horizontal_breaks[i+1][0] - horizontal_breaks[i][0]
      vavg += vertical_breaks[i+1][0] - vertical_breaks[i][0]
  havg /= 4
  vavg /= 4

  # Assuming the first point is accurate
  start = [horizontal_breaks[0][0], vertical_breaks[0][0]]
  targets = [[int(start[0] + x * havg), vertical_breaks[y][0]] for x in range(8) for y in range(4)]
  return targets

def compare_card_at(pixels, x, y, card):
    acc = 0
    for i in range(0, 128, 3):
        for j in range(0, 128, 3):
            r_diff = abs(pixels[i+x, j+y][0] - card[i, j][0])
            g_diff = abs(pixels[i+x, j+y][1] - card[i, j][1])
            b_diff = abs(pixels[i+x, j+y][2] - card[i, j][2])
            acc += sqrt((r_diff**2+g_diff**2+b_diff**2))/3
    return acc

def match_card_at(pixels, x, y, attr, ranked_up = 0, rarity_set = {'UR', 'SSR', 'SR'}):
    if attr == 'NONE':
        return [0, 0]
    best = [0, 0] # is_rankup, card_num
    best_val = 99999999
    for n in range(1, total_cards + 1):
        if cards[str(n)]['rarity'] not in rarity_set:
            continue
        if cards[str(n)]['attribute'] != attr:
            continue
        if ranked_up == 0:
            normal_val = compare_card_at(pixels, x, y, normals[n-1])
            if normal_val < best_val:
                best_val = normal_val
                best = [0, n]
        if ranked_up == 1:
            rankup_val = compare_card_at(pixels, x, y, rankups[n-1])
            if rankup_val < best_val:
                best_val = rankup_val
                best = [1, n]
    return best

def get_icon_color(pixels, x, y):
    totalr = 0
    totalg = 0
    totalb = 0
    for i in range(x + 1, x + 9):
        for j in range(y + 56, y + 56 + 8):
            totalr += pixels[i, j][0] 
            totalg += pixels[i, j][1] 
            totalb += pixels[i, j][2]
    totalr /= 64
    totalg /= 64
    totalb /= 64
    if totalr + totalg + totalb >= 250*3:
        return 'NONE'
    if totalr == max([totalr, totalg, totalb]):
        return 'smile'
    elif totalg == max([totalr, totalg, totalb]):
        return 'pure'
    else:
        return 'cool'

def get_icon_rankup(pixels, x, y):
    totalr = 0
    totalg = 0
    totalb = 0
    for i in range(5, 7):
        for j in range(30, 32):
            totalr += pixels[x+i, y+j][0]
            totalg += pixels[x+i, y+j][1]
            totalb += pixels[x+i, y+j][2]
    totalr /= 4
    totalg /= 4
    totalb /= 4
    if sqrt((totalr - 248)**2 + (totalg - 219)**2 + (totalb - 108)**2) <= 40:
        return 1
    return 0

def match_cards(pixels, targets, rarity_set = {'UR', 'SSR', 'SR'}):
    team = []
    curr = 1
    start = time.time()
    print("Matching... ")
    for point in targets:
        print('{0} / {1}'.format(curr, len(targets)))
        point_color = get_icon_color(pixels, point[0], point[1])
        point_rankup = get_icon_rankup(pixels, point[0], point[1])
        curr_card = match_card_at(pixels, point[0], point[1], 
                                  point_color, point_rankup, rarity_set)
        if curr_card[1] != 0:
            team.append(curr_card)
        curr += 1
    print('Time elapsed: {0} seconds'.format(time.time() - start))
    return team

normals = []
rankups = []
def preload_cards():
  for i in range(1, total_cards + 1):
    normals.append(
        Image.open('static/icon/normal/{0}.png'.format(str(i))).load())
    rankups.append(
        Image.open('static/icon/rankup/{0}.png'.format(str(i))).load())

def main(path, rarity_set):
  try:
    preload_cards()
  except e as BaseException:
    sys.exit("Error loading static icon data.")
    return

  try:
    img = Image.open(path)
    pixels = img.load()
  except e as BaseException:
    sys.exit("Error when loading the image.")
    return

  output_path = SCALED_OUTPUT_PATH_PREFIX + os.path.basename(path)
  scaled_img = rescale_image(img, pixels, OUTPUT_MODE, output_path = output_path)
  scaled_pixels = scaled_img.load()
  targets = get_targets(scaled_img, scaled_pixels)
  team = match_cards(scaled_pixels, targets, rarity_set)

  # Print out the team
  print("")
  print("===========OUTPUT============")
  print("")
  i = 0
  file_output = ""
  for member in team:
    mezame = "" if member[0] == 0 else "[觉醒] "

    out_str = "{0}:　{1}{2} {3} {4}".format(
                i+1,
                mezame,
                member[1],
                cards[str(member[1])]['rarity'],
                cards[str(member[1])]['name']
              )
    file_output += out_str + "\n"
    print(out_str)
    i += 1

  try:
    file = io.open(JSON_OUTPUT_PATH_PREFIX + os.path.basename(path) + ".out", 'w')
    file.write(file_output)
    file.close()
  except e as BaseException:
    sys.exit("Error writing output file.")

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument("file", help="The path to the screenshot.")
  parser.add_argument("--ur", help="Includes UR cards in the matching process.", action="store_true")
  parser.add_argument("--ssr", help="Includes SSR cards in the matching process.", action="store_true")
  parser.add_argument("--sr", help="Includes SR cards in the matching process.", action="store_true")
  parser.add_argument("--r", help="Includes R cards in the matching process.", action="store_true")
  parser.add_argument("--n", help="Includes N cards in the matching process.", action="store_true")
  args = parser.parse_args()

  rarity_set = set()
  if args.ur:
    rarity_set.add("UR")
  if args.ssr:
    rarity_set.add("SSR")
  if args.sr:
    rarity_set.add("SR")
  if args.r:
    rarity_set.add("R")
  if args.n:
    rarity_set.add("N")

  if len(rarity_set) == 0:
    sys.exit("Must specify at least one rarity!")

  main(args.file, rarity_set)